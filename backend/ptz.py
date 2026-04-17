"""PTZ control endpoints using pytapo."""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pytapo import Tapo

from backend.config import get_settings

router = APIRouter(prefix="/ptz", tags=["ptz"])

# Map request direction to (x_coord, y_coord) unit vectors for moveMotor.
# x positive = right, y positive = up (Tapo convention).
_DIRECTION: dict[str, tuple[int, int]] = {
    "up": (0, 10),
    "down": (0, -10),
    "left": (-10, 0),
    "right": (10, 0),
}


def _get_tapo() -> Tapo:
    s = get_settings()
    return Tapo(s.tapo_host, s.tapo_user, s.tapo_pass)


async def _run(fn, *args):
    """Run a blocking pytapo call in the default thread-pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


class MoveRequest(BaseModel):
    direction: Literal["up", "down", "left", "right"]
    steps: int = Field(default=1, ge=1, le=20)


@router.post("/move")
async def move(req: MoveRequest):
    """Move the camera in *direction* for *steps* increments."""
    x, y = _DIRECTION[req.direction]
    try:
        tapo = _get_tapo()
        await _run(tapo.moveMotor, x * req.steps, y * req.steps)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok", "direction": req.direction, "steps": req.steps}


@router.post("/stop")
async def stop():
    """Send a zero-delta move to halt any in-progress motor movement."""
    try:
        tapo = _get_tapo()
        await _run(tapo.moveMotor, 0, 0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok"}


@router.get("/presets")
async def get_presets():
    """Return all saved PTZ presets."""
    try:
        tapo = _get_tapo()
        presets = await _run(tapo.getPresets)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return presets


@router.post("/preset/{preset_id}")
async def go_to_preset(preset_id: int):
    """Move to a saved preset by ID."""
    try:
        tapo = _get_tapo()
        await _run(tapo.setPreset, str(preset_id))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok", "preset_id": preset_id}
