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


class ConfigPutIn(BaseModel):
    section: str
    changes: dict[str, Any]


def _validate_range(field: FieldDef, value: Any) -> str | None:
    """Comprueba tipo/rango/enum de un valor contra su FieldDef, sin reinventar rangos:
    usa exactamente field.min/field.max/field.enum_values/field.max_length del esquema."""
    if field.type == "bool":
        if not isinstance(value, bool):
            return "Debe ser verdadero o falso."
        return None

    if field.type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return "Debe ser un número entero."
    elif field.type == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "Debe ser un número."
    elif field.type == "enum":
        if field.enum_values is not None and value not in field.enum_values:
            return f"Debe ser uno de: {', '.join(field.enum_values)}."
        return None
    elif field.type in ("list_int", "list_str"):
        if not isinstance(value, list):
            return "Debe ser una lista."
        item_type = int if field.type == "list_int" else str
        if not all(isinstance(v, item_type) and not isinstance(v, bool) for v in value):
            return "Todos los elementos de la lista deben tener el tipo correcto."
        return None
    elif field.type == "time":
        import re
        if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
            return "Debe tener formato HH:MM."
        return None
    else:  # "str"
        if not isinstance(value, str):
            return "Debe ser una cadena de texto."
        if field.max_length is not None and len(value) > field.max_length:
            return f"No puede superar los {field.max_length} caracteres."
        return None

    if field.min is not None and field.max is not None:
        if not field.min <= value <= field.max:
            return f"Debe estar entre {field.min} y {field.max}."
    elif field.min is not None and value < field.min:
        return f"Debe ser mayor o igual que {field.min}."
    elif field.max is not None and value > field.max:
        return f"Debe ser menor o igual que {field.max}."
    return None


def _validate_yolo_classes(ids: Any) -> str | None:
    """Reutiliza LITERALMENTE las 4 comprobaciones de detection.py:88-105 — no una
    redaccion paralela que pudiera divergir (T-32-10)."""
    if not isinstance(ids, list):
        return "Debe ser una lista de números enteros."
    if not ids:
        return (
            "La lista de clases no puede estar vacia: con classes=[] el detector "
            "devuelve 0 detecciones y el sistema se queda ciego en silencio, sin "
            "errores ni logs."
        )
    if any(not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= 79 for c in ids):
        return "Cada clase debe ser un id COCO entre 0 y 79."
    if len(set(ids)) != len(ids):
        return "La lista de clases no puede tener duplicados."
    if 0 not in ids:
        return (
            "La clase 'person' (0) no se puede desactivar: sin ella dejarian de "
            "funcionar el conteo de linea, el reconocimiento facial, la "
            "re-identificacion y los eventos de comportamiento."
        )
    return None


@router.put("")
@limiter.limit(V2_RATE_LIMIT)
async def put_config(request: Request, body: ConfigPutIn) -> dict[str, Any]:
    section = next((s for s in ALL_SECTIONS if s.key == body.section), None)
    if section is None:
        raise HTTPException(404, detail=f"Sección desconocida: {body.section}")

    errors: list[dict[str, str]] = []
    valid_changes: dict[str, Any] = {}
    for key, value in body.changes.items():
        f = field_by_key(key)
        if f is None:
            errors.append({"field": key, "message": "Campo desconocido."})
            continue
        if f.secret or f.readonly:
            errors.append({
                "field": key,
                "message": "Este campo no es editable desde la interfaz.",
            })
            continue
        per_field_error = (
            _validate_yolo_classes(value) if key == "yolo_classes"
            else _validate_range(f, value)
        )
        if per_field_error:
            errors.append({"field": key, "message": per_field_error})
            continue
        valid_changes[key] = value

    settings = get_settings()
    overrides = await _config_repo().get_all()
    if valid_changes:
        try:
            build_candidate_settings(settings, overrides, valid_changes)
        except ValidationError as e:
            for err in e.errors():
                fkey = str(err["loc"][0]) if err["loc"] else body.section
                msg = err["msg"]
                if not any(x["field"] == fkey for x in errors):
                    errors.append({"field": fkey, "message": msg})
                # Si el campo cruzado no estaba en valid_changes, sacarlo igualmente
                # para no dejar una mitad invalida a medio persistir.
                valid_changes.pop(fkey, None)

    if errors:
        raise HTTPException(422, detail={"errors": errors})

    diff: dict[str, dict[str, Any]] = {}
    requires_restart: list[str] = []
    for key, value in valid_changes.items():
        f = field_by_key(key)
        before = overrides[key] if key in overrides else getattr(settings, key)
        await _config_repo().set(key, value)     # PERSISTIR ANTES DE PROPAGAR
        diff[key] = {"before": before, "after": value}
        if f.applies != "hot":
            requires_restart.append(key)

    if _camera_manager is not None:
        for pipeline in _camera_manager.all():
            if "yolo_classes" in valid_changes:
                pipeline.set_detection_classes(list(valid_changes["yolo_classes"]))
            if "process_width" in valid_changes or "process_height" in valid_changes:
                w = valid_changes.get(
                    "process_width", overrides.get("process_width", settings.process_width))
                h = valid_changes.get(
                    "process_height", overrides.get("process_height", settings.process_height))
                pipeline.set_process_size(int(w), int(h))

    if _event_engine is not None and diff:
        _event_engine.config_changed(datetime.datetime.now(), section=body.section, diff=diff)

    fresh_overrides = await _config_repo().get_all()
    fields = _section_fields_payload(section, fresh_overrides, get_settings())
    return {"section": body.section, "fields": fields, "requires_restart": requires_restart}


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
