"""PTZ control endpoints using pytapo."""

import asyncio
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


def _tapo_op(method_name: str, *args):
    """
    Instantiate Tapo and call *method_name* inside a worker thread that owns
    a brand-new event loop.

    pytapo calls asyncio.get_event_loop().run_until_complete() internally.
    If the thread inherits FastAPI's running loop that call raises
    "Cannot run the event loop while another loop is running".
    Setting a fresh loop before touching pytapo avoids the clash entirely.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        s = get_settings()
        tapo = Tapo(s.tapo_host, s.tapo_user, s.tapo_pass)
        return getattr(tapo, method_name)(*args)
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
