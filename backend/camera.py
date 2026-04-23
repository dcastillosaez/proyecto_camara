"""Camera settings endpoints — privacy, LED, motion detection, auto-track, reboot, resolution."""

import asyncio
from typing import Any

import supervision as sv
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
_stream_ref = None
_tracker_ref = None


def set_refs(stream, tracker) -> None:
    global _stream_ref, _tracker_ref
    _stream_ref = stream
    _tracker_ref = tracker


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
    if _stream_ref is not None:
        nw, nh = _stream_ref.get_native_resolution()
        if nw > 0:
            native = (nw, nh)
        cw, ch = _stream_ref.get_process_size()
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
    """Change the processing resolution and recalculate the virtual line."""
    if _stream_ref is None or _tracker_ref is None:
        raise HTTPException(status_code=503, detail="Stream not ready")

    s = get_settings()
    target_w = req.width if req.width > 0 else None
    target_h = req.height if req.height > 0 else None

    # Determine effective frame dimensions for line calculation
    if target_w and target_h:
        frame_w, frame_h = target_w, target_h
    else:
        nw, nh = _stream_ref.get_native_resolution()
        frame_w, frame_h = (nw or 1280), (nh or 720)

    # Scale line from fractions to pixels
    new_start = sv.Point(int(s.line_start_x_frac * frame_w), int(s.line_start_y_frac * frame_h))
    new_end   = sv.Point(int(s.line_end_x_frac   * frame_w), int(s.line_end_y_frac   * frame_h))

    _tracker_ref.reconfigure_line(new_start, new_end)
    _stream_ref.set_process_size(req.width, req.height)

    label = f"{req.width}×{req.height}" if req.width > 0 else "Nativa"
    return {"resolution": label, "line_start": [new_start.x, new_start.y], "line_end": [new_end.x, new_end.y]}
