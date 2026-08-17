"""API v2 — configuracion de deteccion: clases activas (Fase 27, BEH-06).

Auth y rate limiting: la app aplica auth globalmente (FastAPI(dependencies=[Depends(verify)])),
asi que los routers incluidos con app.include_router() la heredan automaticamente — no hace
falta Depends(verify) por ruta. El rate limit (SEC-16) usa el limiter/valor compartidos de
backend/api/v2/deps.py.

ATENCION: el PUT de este modulo es el PRIMER endpoint del proyecto que muta la
configuracion del pipeline en caliente. No hay roles en el sistema (la auth es
todo-o-nada), asi que cualquiera con la Basic Auth podria cegar la deteccion. Las tres
mitigaciones son: rate limit compartido, validacion estricta (0..79, no vacia, sin
duplicados, con la clase 0 obligatoria) y un evento CONFIG_CHANGED por cada cambio para
que quede rastro en el historico.

Precedencia de configuracion (27-RESEARCH.md Q6, decision del usuario): la fila de
app_config GANA sobre la env var YOLO_CLASSES, porque es lo ultimo que el operador toco
desde la UI. La env var queda como valor inicial de una instalacion limpia.
"""

from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.config import get_settings
from backend.database import get_session_factory
from backend.storage.repositories import ConfigRepo

router = APIRouter(prefix="/api/v2/detection", tags=["detection"])

_camera_manager: Any = None
_event_engine: Any = None


def configure(camera_manager: Any, event_engine: Any = None) -> None:
    """Wire the live CameraManager/EventEngine instances. Called once from main.py's lifespan."""
    global _camera_manager, _event_engine
    _camera_manager = camera_manager
    _event_engine = event_engine


# Lista blanca: el modelo expone las 80 clases COCO, pero ofrecer las 80 invita a activar
# "tostadora" y degradar el pipeline sin ganancia (27-RESEARCH.md D-4). Estas son las 6 del
# criterio 1 del ROADMAP. Los ids salen de YOLO('yolo26n.pt').names.
AVAILABLE_CLASSES: tuple[tuple[int, str], ...] = (
    (0, "person"), (1, "bicycle"), (2, "car"),
    (3, "motorcycle"), (24, "backpack"), (28, "suitcase"),
)
LOCKED_CLASS_IDS: frozenset[int] = frozenset({0})
CONFIG_KEY = "yolo_classes"


def _config_repo() -> ConfigRepo:
    return ConfigRepo(get_session_factory())


class DetectionClassesIn(BaseModel):
    classes: list[int]


def _classes_payload(active: list[int]) -> dict[str, Any]:
    return {
        "active": list(active),
        "available": [
            {"id": cid, "name": name, "locked": cid in LOCKED_CLASS_IDS}
            for cid, name in AVAILABLE_CLASSES
        ],
        "locked": sorted(LOCKED_CLASS_IDS),
    }


@router.get("/classes")
@limiter.limit(V2_RATE_LIMIT)
async def get_classes(request: Request) -> dict[str, Any]:
    persisted = await _config_repo().get(CONFIG_KEY)
    active = list(persisted) if persisted else list(get_settings().yolo_classes)
    return _classes_payload(active)


@router.put("/classes")
@limiter.limit(V2_RATE_LIMIT)
async def put_classes(request: Request, body: DetectionClassesIn) -> dict[str, Any]:
    ids = body.classes
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="La lista de clases no puede estar vacia: con classes=[] el detector "
                   "devuelve 0 detecciones y el sistema se queda ciego en silencio, sin "
                   "errores ni logs.",
        )
    if any(not isinstance(c, int) or not 0 <= c <= 79 for c in ids):
        raise HTTPException(status_code=400, detail="Cada clase debe ser un id COCO entre 0 y 79.")
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="La lista de clases no puede tener duplicados.")
    if not LOCKED_CLASS_IDS.issubset(ids):
        raise HTTPException(
            status_code=400,
            detail="La clase 'person' (0) no se puede desactivar: sin ella dejarian de "
                   "funcionar el conteo de linea, el reconocimiento facial, la "
                   "re-identificacion y los eventos de comportamiento.",
        )

    # Persistir ANTES de propagar: si el proceso muriera entre ambos pasos, el arranque
    # siguiente (main.py, precedencia app_config > env var) aplicaria lo que el operador
    # pidio en vez de perderlo.
    await _config_repo().set(CONFIG_KEY, list(ids))
    if _camera_manager is not None:
        for pipeline in _camera_manager.all():
            pipeline.set_detection_classes(list(ids))
    if _event_engine is not None:
        _event_engine.config_changed(datetime.datetime.now(), classes=list(ids))

    return _classes_payload(list(ids))
