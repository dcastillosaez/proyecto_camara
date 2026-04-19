"""Google Drive uploader — OAuth2 desktop flow, upload with exponential-backoff retry."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
MAX_RETRIES = 3


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
    """Upload *local_path* to the Drive folder. Returns the Drive file ID."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = load_credentials(credentials_path, token_path)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    name = Path(local_path).name
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaFileUpload(local_path, mimetype="video/mp4", resumable=True)
    result = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return result["id"]


class DriveUploader:
    """
    Background thread that drains a queue of clip paths and uploads each to Google Drive.
    Calls *on_uploaded(local_path, gdrive_id)* on success — local file is then deleted.
    Calls *on_failed(local_path)* after MAX_RETRIES failed attempts.
    """

    def __init__(
        self,
        folder_id: str,
        credentials_path: str = "credentials.json",
        token_path: str = "data/token.json",
        on_uploaded: Callable[[str, str], None] | None = None,
        on_failed: Callable[[str], None] | None = None,
    ) -> None:
        self._folder_id = folder_id
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._on_uploaded = on_uploaded
        self._on_failed = on_failed
        self._queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._creds_available = os.path.exists(credentials_path)

    @property
    def credentials_available(self) -> bool:
        return self._creds_available

    def enqueue(self, local_path: str) -> None:
        self._queue.put(local_path)

    def start(self) -> None:
        if not self._creds_available:
            logger.warning(
                "DriveUploader: %s not found — uploads disabled. "
                "Download OAuth 2.0 Desktop credentials from Google Cloud Console "
                "and save as credentials.json in the project root.",
                self._credentials_path,
            )
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="drive-uploader")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            try:
                path = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            self._upload_with_retry(path)

    def _upload_with_retry(self, path: str) -> None:
        if not self._creds_available:
            logger.warning("DriveUploader: no credentials.json — skipping %s", path)
            if self._on_failed:
                self._on_failed(path)
            return

        for attempt in range(MAX_RETRIES):
            try:
                gdrive_id = upload_file(
                    path, self._folder_id, self._credentials_path, self._token_path
                )
                logger.info("DriveUploader: %s → drive:%s", path, gdrive_id)
                try:
                    os.remove(path)
                    logger.info("DriveUploader: deleted local clip %s", path)
                except OSError as exc:
                    logger.warning("DriveUploader: could not delete %s: %s", path, exc)
                if self._on_uploaded:
                    self._on_uploaded(path, gdrive_id)
                return
            except Exception as exc:
                delay = 2 ** attempt
                logger.warning(
                    "DriveUploader: attempt %d/%d failed (%s) — retry in %ds",
                    attempt + 1, MAX_RETRIES, exc, delay,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)

        logger.error("DriveUploader: all retries exhausted for %s", path)
        if self._on_failed:
            self._on_failed(path)
