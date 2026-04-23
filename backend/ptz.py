"""PTZ control endpoints using pytapo."""

import asyncio
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pytapo import Tapo

from backend.config import get_settings

router = APIRouter(prefix="/ptz", tags=["ptz"])

_DIRECTION: dict[str, tuple[int, int]] = {
    "up": (0, 10),
    "down": (0, -10),
    "left": (-10, 0),
    "right": (10, 0),
}

# Shared Tapo instance — recreated on failure to avoid stale connections.
# Lock serializes all calls so the camera never sees parallel auth attempts
# (which it interprets as brute-force and triggers a Temporary Suspension).
_tapo_instance: Tapo | None = None
_tapo_lock = threading.Lock()


def _get_tapo() -> Tapo:
    global _tapo_instance
    if _tapo_instance is None:
        s = get_settings()
        _tapo_instance = Tapo(s.tapo_host, s.tapo_user, s.tapo_pass)
    return _tapo_instance


def _tapo_op(method_name: str, *args):
    """
    Call *method_name* on the shared Tapo singleton inside a worker thread
    that owns a fresh event loop (pytapo calls run_until_complete internally).

    The module-level lock ensures only one call runs at a time, preventing
    the parallel-auth issue that triggers camera Temporary Suspension.
    On any exception the singleton is discarded so the next call reconnects.
    """
    global _tapo_instance
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        with _tapo_lock:
            tapo = _get_tapo()
            return getattr(tapo, method_name)(*args)
    except Exception:
        _tapo_instance = None  # force reconnect on next call
        raise
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def _ptz(method_name: str, *args):
    """Offload a pytapo call to a worker thread with an isolated event loop."""
    return await asyncio.to_thread(_tapo_op, method_name, *args)


class MoveRequest(BaseModel):
    direction: Literal["up", "down", "left", "right"]
    steps: int = Field(default=1, ge=1, le=20)


@router.post("/move")
async def move(req: MoveRequest):
    """Move the camera in *direction* for *steps* increments."""
    x, y = _DIRECTION[req.direction]
    try:
        await _ptz("moveMotor", x * req.steps, y * req.steps)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok", "direction": req.direction, "steps": req.steps}


@router.post("/stop")
async def stop():
    """Send a zero-delta move to halt any in-progress motor movement."""
    try:
        await _ptz("moveMotor", 0, 0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok"}


@router.get("/presets")
async def get_presets():
    """Return all saved PTZ presets."""
    try:
        presets = await _ptz("getPresets")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return presets


@router.post("/preset/{preset_id}")
async def go_to_preset(preset_id: int):
    """Move to a saved preset by ID."""
    try:
        await _ptz("setPreset", str(preset_id))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok", "preset_id": preset_id}


class SavePresetRequest(BaseModel):
    name: str


@router.post("/save_preset")
async def save_preset(req: SavePresetRequest):
    """Save the current motor position as a new preset with the given name."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        await _ptz("savePreset", name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok", "name": name}
