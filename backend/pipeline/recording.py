"""RecordingWorker — feeds a RingFrameBuffer continuously and assembles clips
with pre/post-buffer context around triggering events (Fase 20, ADR-07).

Two threads:
  _feed_loop      broker -> RingFrameBuffer (always) + live queue (while a clip is active)
  _assembly_loop  drains the pre-buffer, writes the clip, extends its deadline on
                  new requests instead of opening a second overlapping clip, and
                  keeps writing live frames until post_buffer_secs after the last
                  request — all off the capture critical path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import cv2
import numpy as np

from backend.pipeline.prebuffer import BufferedFrame, RingFrameBuffer
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry
from backend.recorder import ClipWriter

if TYPE_CHECKING:
    from backend.pipeline.broker import Frame, Subscription

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


@dataclass
class ClipRequest:
    reason: str
    trigger_ts: datetime
    trigger_event_id: str | None = None
    person_id: int | None = None
    zone_id: str | None = None
    severity: str = "info"
    pre_secs: float | None = None      # DIR-02: por regla; None = todo el pre-buffer
    post_secs: float | None = None     # DIR-02: por regla; None = post_buffer_secs
    force_upload: bool = False         # DIR-02: accion upload_drive


@dataclass
class ClipResult:
    path: str
    started_at: datetime
    ended_at: datetime
    reason: str
    trigger_event_id: str | None
    person_id: int | None
    zone_id: str | None
    duration_s: float
    size_bytes: int
    sha256: str
    thumbnail_path: str | None
    upload_state: str
    frames: int = 0


@dataclass
class _ActiveClip:
    writer: ClipWriter
    started_at: datetime
    deadline: float          # time.monotonic() (BUG-07): inmune a cambios de hora y NTP
    request: ClipRequest
    trigger_jpeg: bytes | None = None
    final_path: str = ""     # BUG-08: se escribe en writer.path (.part.mp4) y se renombra
    opened_at: float = 0.0   # time.monotonic() de apertura, para la duracion maxima (BUG-11)
    last_seq: int = -1       # ultimo frame escrito: evita duplicados pre-buffer/directo
    next_slot: float | None = None   # ritmo de escritura en reloj de captura (BUG-10)
    frames: int = 0
    force_upload: bool = False


PART_SUFFIX = ".part.mp4"


def probe_clip(path: str) -> dict[str, float] | None:
    """FPS declarado, frames y duracion del clip segun ffprobe (BUG-10).

    ffprobe no es una dependencia de Python: si no esta en el PATH devuelve None y
    no pasa nada. Sirve para comprobar que el clip dura lo que duro la escena."""
    exe = shutil.which("ffprobe")
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=r_frame_rate,nb_read_frames:format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        data = json.loads(out)
        stream = data["streams"][0]
        num, den = stream["r_frame_rate"].split("/")
        return {
            "fps": float(num) / float(den),
            "frames": float(stream["nb_read_frames"]),
            "duration_s": float(data["format"]["duration"]),
        }
    except Exception:
        logger.debug("ffprobe no pudo leer %s", path, exc_info=True)
        return None


class RecordingWorker:
    def __init__(
        self,
        sub: Subscription,
        registry: TrackRegistry,
        clips_dir: str = "data/clips",
        thumbnails_dir: str = "data/thumbnails",
        fps: float = 15.0,
        pre_buffer_secs: float = 10.0,
        post_buffer_secs: float = 10.0,
        pre_buffer_max_mb: int = 48,
        pre_buffer_jpeg_quality: int = 85,
        codec: str = "mp4v",
        thumbnail_width: int = 320,
        upload_min_severity: str = "warning",
        on_clip_ready: Callable[[ClipResult], None] | None = None,
        on_failure: Callable[[str], None] | None = None,
        live_queue_max: int = 0,
        max_clip_secs: float = 300.0,
        min_free_mb: int = 1024,
    ) -> None:
        self._sub = sub
        self._registry = registry
        self._clips_dir = Path(clips_dir)
        self._thumbnails_dir = Path(thumbnails_dir)
        self._fps = fps
        self._post_buffer_secs = post_buffer_secs
        self._codec = codec
        self._thumbnail_width = thumbnail_width
        self._upload_min_severity = upload_min_severity
        self._on_clip_ready = on_clip_ready
        self._on_failure = on_failure
        self._max_clip_secs = max_clip_secs     # BUG-11: 0 = sin limite
        self._min_free_mb = min_free_mb         # BUG-11: 0 = sin comprobar
        self._disk_low = False
        self._last_disk_check = 0.0

        self._prebuffer = RingFrameBuffer(
            seconds=pre_buffer_secs, fps=fps,
            max_bytes=pre_buffer_max_mb * 1024 * 1024,
            quality=pre_buffer_jpeg_quality,
        )
        self._rate = AdaptiveRate(target_fps=fps, min_fps=fps, max_fps=fps)

        self._requests: queue.Queue[ClipRequest] = queue.Queue()
        max_live = live_queue_max or max(1, int(fps * (post_buffer_secs + 30)))
        self._live_queue: queue.Queue = queue.Queue(maxsize=max_live)
        self._live_dropped = 0

        self._frame_size: tuple[int, int] = (1280, 720)
        self._running = False
        self._feed_thread: threading.Thread | None = None
        self._assembly_thread: threading.Thread | None = None
        self._active: _ActiveClip | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._feed_thread = threading.Thread(target=self._feed_loop, daemon=True, name="recording-feed")
        self._assembly_thread = threading.Thread(target=self._assembly_loop, daemon=True, name="recording-assembly")
        self._feed_thread.start()
        self._assembly_thread.start()

    def is_alive(self) -> bool:
        """True if both worker threads are still running (queried by WorkerSupervisor)."""
        return bool(
            self._feed_thread is not None and self._feed_thread.is_alive()
            and self._assembly_thread is not None and self._assembly_thread.is_alive()
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        for t in (self._feed_thread, self._assembly_thread):
            if t is not None:
                t.join(timeout)
                if t.is_alive():
                    logger.warning("RecordingWorker: %s did not stop within %.1fs", t.name, timeout)
        self._sub.close()

    def request_clip(
        self,
        reason: str,
        trigger_ts: datetime,
        trigger_event_id: str | None = None,
        person_id: int | None = None,
        zone_id: str | None = None,
        severity: str = "info",
        pre_secs: float | None = None,
        post_secs: float | None = None,
        force_upload: bool = False,
    ) -> None:
        """Start or extend the active clip. Thread-safe — callable from the asyncio loop."""
        self._requests.put_nowait(ClipRequest(
            reason, trigger_ts, trigger_event_id, person_id, zone_id, severity,
            pre_secs=pre_secs, post_secs=post_secs, force_upload=force_upload,
        ))

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "prebuffer_bytes": self._prebuffer.bytes_used,
            "prebuffer_span_seconds": self._prebuffer.span_seconds,
            "live_dropped": self._live_dropped,
            "clip_active": self._active is not None,
            "disk_low": self._disk_low,
            "requests_queue_depth": self._requests.qsize(),
            **self._rate.stats,
        }

    # ------------------------------------------------------------------
    # Feed thread: broker -> prebuffer (+ live queue while a clip is active)
    # ------------------------------------------------------------------

    def _feed_loop(self) -> None:
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                if self._sub.closed:   # BUG-06: reemplazado o parado, nunca en bucle activo
                    break
                continue
            if not self._rate.should_process(time.monotonic()):
                continue
            t0 = time.monotonic()

            h, w = frame.image.shape[:2]
            self._frame_size = (w, h)
            self._prebuffer.push(frame)
            if self._active is not None:
                self._offer_live(frame)

            self._rate.observe(time.monotonic() - t0)

    def _offer_live(self, frame: Frame) -> None:
        try:
            self._live_queue.put_nowait(frame)
            return
        except queue.Full:
            pass
        try:
            self._live_queue.get_nowait()
            self._live_dropped += 1
        except queue.Empty:
            pass
        try:
            self._live_queue.put_nowait(frame)
        except queue.Full:
            pass

    # ------------------------------------------------------------------
    # Assembly thread: state machine (idle <-> recording)
    # ------------------------------------------------------------------

    def _assembly_loop(self) -> None:
        while self._running:
            if self._active is None:
                try:
                    req = self._requests.get(timeout=0.5)
                except queue.Empty:
                    continue
                self._begin_clip(req)
            else:
                try:
                    req = self._requests.get(timeout=0.1)
                    self._extend_clip(req)
                except queue.Empty:
                    pass
                self._drain_live_frames()
                if self._active is not None and self._should_close(self._active):
                    self._finalize_clip()

        if self._active is not None:
            self._finalize_clip()

    def _report_failure(self, message: str) -> None:
        logger.error("RecordingWorker: %s", message)
        if self._on_failure:
            try:
                self._on_failure(message)
            except Exception:
                logger.exception("RecordingWorker: on_failure raised")

    def _disk_is_low(self) -> bool:
        """BUG-11: True si queda menos de min_free_mb en el disco de los clips. Se mira
        como mucho cada 5 s y se avisa una vez por episodio, no en cada peticion."""
        if self._min_free_mb <= 0:
            return False
        now = time.monotonic()
        if now - self._last_disk_check < 5.0 and self._last_disk_check:
            return self._disk_low
        self._last_disk_check = now
        try:
            free_mb = shutil.disk_usage(self._clips_dir).free / (1024 * 1024)
        except OSError:
            return self._disk_low
        low = free_mb < self._min_free_mb
        if low and not self._disk_low:
            self._report_failure(
                f"disco casi lleno ({free_mb:.0f} MB libres < {self._min_free_mb} MB): "
                "grabacion detenida"
            )
        elif not low and self._disk_low:
            logger.info("RecordingWorker: hay espacio otra vez (%.0f MB libres)", free_mb)
        self._disk_low = low
        return low

    def _should_close(self, active: _ActiveClip) -> bool:
        now = time.monotonic()
        if now >= active.deadline:
            return True
        if self._max_clip_secs > 0 and now - active.opened_at >= self._max_clip_secs:
            logger.info("RecordingWorker: clip %s alcanza la duracion maxima (%.0fs)",
                        active.final_path, self._max_clip_secs)
            return True
        return self._disk_is_low()

    def _unique_clip_path(self, req: ClipRequest) -> str:
        """BUG-08: dos clips en el mismo segundo ya no se pisan."""
        stem = f"clip_{req.trigger_ts.strftime('%Y%m%d_%H%M%S')}"
        path = self._clips_dir / f"{stem}.mp4"
        n = 1
        while path.exists() or path.with_name(path.stem + PART_SUFFIX).exists():
            path = self._clips_dir / f"{stem}_{n}.mp4"
            n += 1
        return str(path)

    def _write_paced(self, active: _ActiveClip, captured_at: float, write: Callable[[], None]) -> None:
        """BUG-10: el VideoWriter declara self._fps, pero los frames llegan al ritmo de la
        fuente. Se escribe cada frame tantas veces como huecos de 1/fps cubre en el reloj
        de captura: con una fuente mas lenta el clip ya no se reproduce acelerado y con
        una mas rapida no se ralentiza. Un corte largo (camara caida) no se rellena con
        mas de 2 s de frame congelado."""
        interval = 1.0 / self._fps
        if active.next_slot is None or captured_at <= 0:
            active.next_slot = captured_at
        if captured_at - active.next_slot > 2.0:
            active.next_slot = captured_at
        written = 0
        while active.next_slot <= captured_at + interval / 2:
            write()
            written += 1
            active.next_slot += interval
        active.frames += written

    def _begin_clip(self, req: ClipRequest) -> None:
        if self._disk_is_low():
            return
        final_path = self._unique_clip_path(req)
        part_path = final_path[: -len(".mp4")] + PART_SUFFIX
        writer = ClipWriter(part_path, self._fps, self._frame_size, self._codec)
        if not writer.is_opened:
            self._report_failure(f"VideoWriter failed to open {part_path}")
            return

        # Drop any live frames left over from a previous clip before starting this one.
        while True:
            try:
                self._live_queue.get_nowait()
            except queue.Empty:
                break

        # BUG-10: el clip se activa ANTES de vaciar el pre-buffer. Antes se hacia despues
        # y los frames capturados en medio no iban ni al pre-buffer leido ni a la cola en
        # directo: quedaba un hueco justo tras el disparo. Lo que llegue por las dos vias
        # se escribe una sola vez gracias a last_seq.
        active = _ActiveClip(
            writer=writer, started_at=req.trigger_ts, deadline=self._deadline_for(req),
            request=req, final_path=final_path, opened_at=time.monotonic(),
            force_upload=req.force_upload,
        )
        self._active = active
        pre_frames = self._prebuffer.drain()
        if req.pre_secs is not None:
            since = req.trigger_ts - timedelta(seconds=max(0.0, req.pre_secs))
            pre_frames = [f for f in pre_frames if f.wall_clock >= since]
        for item in pre_frames:
            self._write_paced(active, item.captured_at, lambda j=item.jpeg: writer.write_jpeg(j))
            active.last_seq = max(active.last_seq, item.seq)
        if pre_frames:
            active.started_at = pre_frames[0].wall_clock
        active.trigger_jpeg = self._closest_jpeg(pre_frames, req.trigger_ts)

    @staticmethod
    def _closest_jpeg(pre_frames: list[BufferedFrame], ts: datetime) -> bytes | None:
        """The pre-buffer frame closest to the trigger timestamp — the thumbnail source
        (the event frame has the relevant content, not necessarily the first buffered one)."""
        if not pre_frames:
            return None
        closest = min(pre_frames, key=lambda item: abs((item.wall_clock - ts).total_seconds()))
        return closest.jpeg

    def _deadline_for(self, req: ClipRequest) -> float:
        """Fin del post-buffer en reloj monotonico. BUG-07: con datetime.now() un cambio
        de hora (fin del horario de verano) alargaba el clip una hora entera o lo cerraba
        al instante. La edad del disparo se descuenta una vez, al recibir la peticion; si
        el reloj de pared ha ido hacia atras y sale negativa, cuenta como 0."""
        age = max(0.0, (datetime.now() - req.trigger_ts).total_seconds())
        post = self._post_buffer_secs if req.post_secs is None else max(0.0, req.post_secs)
        return time.monotonic() + max(0.0, post - age)

    def _extend_clip(self, req: ClipRequest) -> None:
        if self._active is None:
            return
        new_deadline = self._deadline_for(req)
        if new_deadline > self._active.deadline:
            self._active.deadline = new_deadline
        # BUG-10: el clip conserva la severidad MAS ALTA de las peticiones que lo
        # extienden. Antes mandaba la primera, y un clip abierto por un evento INFO y
        # extendido por una intrusion CRITICAL no se subia a Drive.
        current = self._active.request
        if _SEVERITY_RANK.get(req.severity, 0) > _SEVERITY_RANK.get(current.severity, 0):
            current.severity = req.severity
        self._active.force_upload = self._active.force_upload or req.force_upload

    def _drain_live_frames(self) -> None:
        if self._active is None:
            return
        while True:
            try:
                frame = self._live_queue.get_nowait()
            except queue.Empty:
                return
            active = self._active
            if frame.seq <= active.last_seq:
                continue            # ya escrito desde el pre-buffer
            active.last_seq = frame.seq
            self._write_paced(active, frame.captured_at,
                              lambda img=frame.image: active.writer.write_image(img))

    def _finalize_clip(self) -> None:
        active = self._active
        self._active = None
        if active is None:
            return
        active.writer.release()
        ended_at = datetime.now()
        # BUG-08: el clip se escribe como .part.mp4 y solo se renombra al cerrarlo; un
        # .part que quede en disco es un clip interrumpido, nunca uno a medias con nombre
        # definitivo. La reconciliacion del arranque los limpia.
        path = active.final_path or active.writer.path
        if active.writer.path != path:
            try:
                os.replace(active.writer.path, path)
            except OSError as exc:
                self._report_failure(f"no se pudo cerrar el clip {path}: {exc}")
                return

        rank = _SEVERITY_RANK.get(active.request.severity, 0)
        min_rank = _SEVERITY_RANK.get(self._upload_min_severity, 1)
        upload_state = "pending" if (rank >= min_rank or active.force_upload) else "skipped"

        result = ClipResult(
            path=path,
            started_at=active.started_at,
            ended_at=ended_at,
            reason=active.request.reason,
            trigger_event_id=active.request.trigger_event_id,
            person_id=active.request.person_id,
            zone_id=active.request.zone_id,
            duration_s=(ended_at - active.started_at).total_seconds(),
            size_bytes=os.path.getsize(path) if os.path.exists(path) else 0,
            sha256=self._sha256_file(path) if os.path.exists(path) else "",
            thumbnail_path=self._save_thumbnail(active),
            upload_state=upload_state,
            frames=active.frames,
        )
        logger.info("RecordingWorker: clip ready %s (%d frames, %.1fs)",
                    result.path, result.frames, result.duration_s)
        if self._on_clip_ready:
            try:
                self._on_clip_ready(result)
            except Exception:
                logger.exception("RecordingWorker: on_clip_ready raised")

    @staticmethod
    def _sha256_file(path: str, block_size: int = 65536) -> str:
        """Streamed — never loads the file into memory whole (clips can be tens of MB)."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(block_size), b""):
                h.update(chunk)
        return h.hexdigest()

    def _save_thumbnail(self, active: _ActiveClip) -> str | None:
        """Thumbnail from the trigger frame (the relevant content), not the clip's first frame."""
        if active.trigger_jpeg is None:
            return None
        image = cv2.imdecode(np.frombuffer(active.trigger_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        h, w = image.shape[:2]
        if w > self._thumbnail_width:
            scale = self._thumbnail_width / w
            image = cv2.resize(image, (self._thumbnail_width, max(1, int(h * scale))))
        stem = Path(active.final_path or active.writer.path).stem
        thumb_path = str(self._thumbnails_dir / f"{stem}.jpg")
        if not cv2.imwrite(thumb_path, image):
            return None
        return thumb_path
