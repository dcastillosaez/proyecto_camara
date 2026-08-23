"""API v2 — GET/PUT /api/v2/config + restore por seccion (Fase 32, OPS-18..20, SET-01..04).

Es el unico router HTTP nuevo de la Fase 32: convierte el esquema declarativo puro de
`backend/api/v2/config_schema.py` (32-01) en un endpoint real. GET resuelve
valor/origen/aplicacion en caliente/secreto por campo sobre las 8 secciones fijas; PUT
valida el lote completo (rango por campo + invariantes cruzados de `Settings`) y devuelve
TODOS los errores 422 a la vez, persiste antes de propagar y aplica en caliente solo las
tres rutas reales (`yolo_classes`, `process_width`, `process_height`); `restore` borra los
overrides `runtime` de una seccion. Todas las vistas de frontend de las waves posteriores
son clientes puros de este router, sin logica de validacion propia (D-04, 32-CONTEXT.md).

Auth y rate limiting: la app aplica auth globalmente (FastAPI(dependencies=[Depends(verify)])),
asi que este router la hereda automaticamente al incluirse con app.include_router() — no
hace falta Depends(verify) por ruta. El rate limit (SEC-16) usa el limiter/valor compartidos
de backend/api/v2/deps.py, mismo molde que detection.py/alerts.py.

Sin roles en el sistema (la auth es todo-o-nada): cualquier credencial Basic Auth valida
puede reescribir 100 de los 112 campos de Settings (todos salvo los 12 `secret`). La unica
mitigacion es auditoria (`CONFIG_CHANGED` con diff) + rate limit + validacion estricta
(T-32-05..T-32-10 del threat model de 32-02-PLAN.md).
"""

from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from backend.api.v2.config_schema import (
    ALL_SECTIONS,
    FieldDef,
    build_candidate_settings,
    field_by_key,
    resolve_origin,
)
from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.config import get_settings
from backend.database import get_session_factory
from backend.storage.repositories import ConfigRepo

router = APIRouter(prefix="/api/v2/config", tags=["config"])

_camera_manager: Any = None
_event_engine: Any = None


def configure(camera_manager: Any, event_engine: Any = None) -> None:
    """Wire the live CameraManager/EventEngine instances. Called once from main.py's lifespan."""
    global _camera_manager, _event_engine
    _camera_manager = camera_manager
    _event_engine = event_engine


def _config_repo() -> ConfigRepo:
    return ConfigRepo(get_session_factory())


def _field_payload(f: FieldDef, overrides: dict[str, Any], settings: Any) -> dict[str, Any]:
    """Construye el FieldValue del contrato GET/PUT/restore a partir de un FieldDef.

    `configured` sale SIEMPRE (secret o no), por uniformidad del futuro settings-field.js
    del frontend, pero solo importa cuando `secret == true` (32-02-PLAN.md, interfaces).
    Campos `secret=True` nunca llevan la clave `value` en el JSON de salida, en ningun
    origin (T-32-05).
    """
    value, origin = resolve_origin(f, overrides, settings)
    payload: dict[str, Any] = {
        "key": f.key,
        "env": f.env,
        "label": f.label,
        "hint": f.hint,
        "type": f.type,
        "default": f.default,
        "min": f.min,
        "max": f.max,
        "step": f.step,
        "enum_values": list(f.enum_values) if f.enum_values else None,
        "origin": origin,
        "applies": f.applies,
        "secret": f.secret,
        "readonly": f.readonly,
        "configured": bool(value),
    }
    if not f.secret:
        payload["value"] = value
    return payload


def _section_fields_payload(section, overrides: dict[str, Any], settings: Any) -> list[dict[str, Any]]:
    return [
        _field_payload(f, overrides, settings)
        for group in section.groups
        for f in group.fields
    ]


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def get_config(request: Request) -> dict[str, Any]:
    overrides = await _config_repo().get_all()
    settings = get_settings()
    sections = []
    for section in ALL_SECTIONS:
        groups = []
        for group in section.groups:
            if group.external_source is not None:
                groups.append({
                    "key": group.key, "label": group.label,
                    "external_source": group.external_source, "fields": [],
                })
            else:
                groups.append({
                    "key": group.key, "label": group.label,
                    "external_source": None,
                    "fields": [_field_payload(f, overrides, settings) for f in group.fields],
                })
        sections.append({"key": section.key, "label": section.label, "groups": groups})
    return {"sections": sections}
