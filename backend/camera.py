"""Camera settings endpoints — privacy, LED, motion detection, auto-track, reboot, resolution."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import get_settings
from backend.ptz import _tapo_op

router = APIRouter(prefix="/camera", tags=["camera"])

# Available processing resolutions (w, h). Native = (0, 0).
RESOLUTIONS: list[tuple[int, int]] = [
    (0,    0),     # Native
    (2304, 1296),  # 2K
    (1920, 1080),  # 1080p
    (1280, 720),   # 720p (default)
    (854,  480),   # 480p
    (640,  360),   # 360p
]

# Runtime reference — injected from main.py at startup
# BUG-03: se guarda el CameraManager y no la pipeline: si la pipeline de la camara se
# recrea (alta/baja en caliente desde /api/v2/cameras), una referencia fija apuntaria
# a la instancia vieja ya parada.
_manager_ref = None
_camera_id = "cam1"


def set_refs(manager, camera_id: str = "cam1") -> None:
    global _manager_ref, _camera_id
    _manager_ref = manager
    _camera_id = camera_id


def _stream():
    return _manager_ref.get(_camera_id) if _manager_ref is not None else None


async def _cam(method: str, *args):
    return await asyncio.to_thread(_tapo_op, method, *args)


# ---------------------------------------------------------------------------
# Status (all toggles in one request)
# ---------------------------------------------------------------------------

@router.get("/status")
async def camera_status():
    """Return current state of all toggleable settings (parallel Tapo calls).

    Returns partial data on individual failures rather than a blanket 502 —
    each field defaults to False and 'errors' lists which calls failed.
    """
    results = await asyncio.gather(
        _cam("getPrivacyMode"),
        _cam("getLED"),
        _cam("getMotionDetection"),
        _cam("getAutoTrackTarget"),
        return_exceptions=True,
    )

    def _bool(d) -> bool:
        if isinstance(d, Exception):
            return False
        if isinstance(d, dict):
            v = d.get("enabled")
            return v not in (None, False, "off", "0", 0, "false")
        return False

    labels = ("privacy", "led", "motion", "autotrack")
    errors = {
        label: str(r)
        for label, r in zip(labels, results)
        if isinstance(r, Exception)
    }

    payload = {label: _bool(r) for label, r in zip(labels, results)}
    if errors:
        payload["errors"] = errors
    return payload


# ---------------------------------------------------------------------------
# Toggle endpoints
# ---------------------------------------------------------------------------

class ToggleRequest(BaseModel):
    enabled: bool


@router.post("/privacy")
async def set_privacy(req: ToggleRequest):
    try:
        await _cam("setPrivacyMode", req.enabled)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"privacy": req.enabled}


@router.post("/led")
async def set_led(req: ToggleRequest):
    try:
        await _cam("setLEDEnabled", req.enabled)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"led": req.enabled}


@router.post("/motion")
async def set_motion(req: ToggleRequest):
    try:
        await _cam("setMotionDetection", req.enabled)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"motion": req.enabled}


@router.post("/autotrack")
async def set_autotrack(req: ToggleRequest):
    try:
        await _cam("setAutoTrackTarget", req.enabled)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"autotrack": req.enabled}


# ---------------------------------------------------------------------------
# Reboot
# ---------------------------------------------------------------------------

@router.post("/reboot")
async def reboot():
    try:
        await _cam("reboot")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "rebooting"}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

class ResolutionRequest(BaseModel):
    width: int
    height: int


@router.get("/resolutions")
async def get_resolutions():
    """Return available processing resolutions and the current one."""
    s = get_settings()

    native = (0, 0)
    current_w, current_h = s.process_width, s.process_height
    stream = _stream()
    if stream is not None:
        nw, nh = stream.get_native_resolution()
        if nw > 0:
            native = (nw, nh)
        cw, ch = stream.get_process_size()
        if cw > 0:
            current_w, current_h = cw, ch

    options = []
    for w, h in RESOLUTIONS:
        label = f"{w}×{h}" if w > 0 else (f"Nativa ({native[0]}×{native[1]})" if native[0] > 0 else "Nativa")
        options.append({"width": w, "height": h, "label": label})

    return {
        "current": {"width": current_w, "height": current_h},
        "native": {"width": native[0], "height": native[1]},
        "options": options,
    }


@router.post("/resolution")
async def set_resolution(req: ResolutionRequest):
    """Change the processing resolution. Las lineas de conteo se recalculan solas
    en el siguiente frame procesado (gate `_line_frame_size != (fw, fh)` de
    DetectionWorker._update_lines, Plan 33-05) — igual que ya ocurria con las
    zonas, este endpoint no necesita tocar el tracker."""
    stream = _stream()
    if stream is None or stream.tracker is None:
        raise HTTPException(status_code=503, detail="Stream not ready")

    await asyncio.to_thread(stream.set_process_size, req.width, req.height)   # PERF-01

    label = f"{req.width}×{req.height}" if req.width > 0 else "Nativa"
    return {"resolution": label}
