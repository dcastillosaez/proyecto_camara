"""Google Drive upload: the blocking API call, and a persistent DB-backed queue
that drives it with backoff (Fase 20).

The queue lives in the database (recordings.upload_state), not in memory — it
survives restarts. googleapiclient is synchronous; every call to upload_file()
runs in a ThreadPoolExecutor, never directly in a coroutine.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from backend.observability.metrics import metrics as _metrics

if TYPE_CHECKING:
    from backend.storage.repositories import RecordingRepo

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Backoff schedule by attempt number (0-indexed). Quota errors wait longer —
# they're the one failure mode where retrying sooner makes things worse.
RETRY_DELAYS = [30, 120, 600, 1800, 3600]
QUOTA_MULTIPLIER = 4


def load_credentials(credentials_path: str, token_path: str):
    """Return valid OAuth2 credentials, launching browser flow on first run."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        Path(token_path).write_text(creds.to_json())
    return creds


def upload_file(local_path: str, folder_id: str, credentials_path: str, token_path: str) -> str:
    """Upload *local_path* to the Drive folder. Returns the Drive file ID.

    Blocking (googleapiclient is synchronous) — always call via an executor.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = load_credentials(credentials_path, token_path)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    name = Path(local_path).name
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaFileUpload(local_path, mimetype="video/mp4", resumable=True)
    result = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return result["id"]


def classify_error(exc: Exception) -> str:
    """'quota' | 'auth' | 'network' — determines the backoff applied on retry."""
    msg = str(exc).lower()
    if "quota" in msg or "ratelimitexceeded" in msg or "429" in msg:
        return "quota"
    if "invalid_grant" in msg or "unauthorized" in msg or "401" in msg or "token" in msg:
        return "auth"
    return "network"


def backoff_delay(attempt: int, error_kind: str) -> float:
    """Seconds to wait before the next attempt. *attempt* is 0-indexed."""
    idx = min(attempt, len(RETRY_DELAYS) - 1)
    delay = RETRY_DELAYS[idx]
    if error_kind == "quota":
        delay *= QUOTA_MULTIPLIER
    return delay


class UploadQueue:
    """Polls RecordingRepo for due 'pending' uploads and uploads them off the event loop.

    Never blocks the caller: run_once() fetches due rows and fires each upload
    as a background task, returning immediately.
    """

    def __init__(
        self,
        repo: RecordingRepo,
        folder_id: str,
        credentials_path: str = "credentials.json",
        token_path: str = "data/token.json",
        max_attempts: int = 5,
        poll_secs: float = 30.0,
        on_permanent_failure: Callable[[int, str, str], Awaitable[None]] | None = None,
        max_workers: int = 2,
    ) -> None:
        self._repo = repo
        self._folder_id = folder_id
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._max_attempts = max_attempts
        self._poll_secs = poll_secs
        self._on_permanent_failure = on_permanent_failure
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="drive-upload")
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        self._executor.shutdown(wait=False)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_secs)
            try:
                await self.run_once()
            except Exception:
                logger.exception("UploadQueue: poll iteration failed")

    async def run_once(self) -> None:
        """Fetch due pending uploads and fire each off in the background."""
        pending = await self._repo.next_pending(limit=5)
        for rec in pending:
            asyncio.create_task(self._process(rec))

    async def _process(self, rec) -> None:
        from backend.storage.repositories import UploadState

        loop = asyncio.get_running_loop()
        local_path = rec.local_path or rec.filename
        try:
            gdrive_id = await loop.run_in_executor(
                self._executor, upload_file, local_path,
                self._folder_id, self._credentials_path, self._token_path,
            )
            await self._repo.mark_upload(rec.id, UploadState.DONE, drive_file_id=gdrive_id)
            logger.info("UploadQueue: recording %s -> drive:%s", rec.id, gdrive_id)
        except Exception as exc:
            kind = classify_error(exc)
            _metrics.upload_failures_total.labels(reason=kind).inc()
            attempts = rec.upload_attempts + 1
            if attempts >= self._max_attempts:
                logger.error("UploadQueue: recording %s failed permanently after %d attempts: %s", rec.id, attempts, exc)
                await self._repo.mark_upload(rec.id, UploadState.FAILED, error=str(exc))
                if self._on_permanent_failure:
                    try:
                        await self._on_permanent_failure(rec.id, rec.camera_id, str(exc))
                    except Exception:
                        logger.exception("UploadQueue: on_permanent_failure raised")
            else:
                delay = backoff_delay(attempts - 1, kind)
                logger.warning(
                    "UploadQueue: recording %s attempt %d/%d failed (%s, %s) — retry in %.0fs",
                    rec.id, attempts, self._max_attempts, kind, exc, delay,
                )
                await self._repo.mark_upload(
                    rec.id, UploadState.PENDING, error=str(exc),
                    next_attempt_at=datetime.now() + timedelta(seconds=delay),
                )
