"""API v2 — esquema declarativo de configuracion runtime (Fase 32, SET-01..SET-04).

Este modulo NO expone ningun endpoint HTTP: es el contrato puro que consume
`backend/api/v2/config.py` (32-02) y, mas adelante, las vistas de Ajustes del
frontend. Describe los 112 campos reales de `backend.config.Settings` — label
en espanol llano, hint, tipo, rango, seccion, aplicacion en caliente y si es
secreto — agrupados en las 8 secciones fijas del UI-SPEC (Camara, Deteccion,
Tracking, Reconocimiento, Zonas, Reglas, Alertas, Almacenamiento).

Precedencia de valores (D-06, dos precedentes reales: `PUT /api/v2/detection/classes`
de la Fase 27 y el silenciado de alertas de la Fase 30): runtime (`app_config`,
via `ConfigRepo`) > `.env` > default del codigo. `resolve_origin()` decide esa
precedencia por campo sin persistir un cuarto estado en ningun sitio nuevo.

Aplicacion en caliente: solo tres campos (`yolo_classes`, `process_width`,
`process_height`) tienen una ruta real hoy (`CameraPipeline.set_detection_classes`/
`set_process_size`, `backend/pipeline/manager.py:322/329/386`). Todo lo demas es
`"restart_camera"` o `"restart_server"` — este modulo solo *senaliza*, no ejecuta
ningun reinicio (D-07).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldDef:
    key: str                      # nombre exacto en Settings y clave en app_config
    env: str                      # nombre de la env var (mayusculas)
    label: str                    # espanol llano, nunca el identificador Python
    hint: str = ""                # pista en prosa, opcional
    type: str = "str"             # "bool"|"int"|"float"|"enum"|"time"|"list_int"|"list_str"|"secret"|"readonly"
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    enum_values: tuple[str, ...] | None = None
    applies: str = "restart_camera"   # "hot" | "restart_camera" | "restart_server"
    secret: bool = False
    readonly: bool = False
    max_length: int | None = None     # solo para type="str"/"list_str" sin rango numerico


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    fields: tuple[FieldDef, ...] = ()
    # Grupos de solo lectura no respaldados por Settings (zonas definidas, reglas
    # cargadas) usan fields=() y se marcan con external_source:
    external_source: str | None = None   # "/api/zones" | "/api/v2/rules" | None


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    groups: tuple[Group, ...] = ()


ALL_SECTIONS: tuple[Section, ...] = ()  # poblado abajo, ver "Definicion de las 8 secciones"


_FIELDS_BY_KEY: dict[str, FieldDef] = {}


def _rebuild_index() -> None:
    """Reconstruye el indice `_FIELDS_BY_KEY` a partir de ALL_SECTIONS.

    Se llama una vez a nivel de modulo, tras definir ALL_SECTIONS con datos.
    """
    _FIELDS_BY_KEY.clear()
    for section in ALL_SECTIONS:
        for group in section.groups:
            for f in group.fields:
                _FIELDS_BY_KEY[f.key] = f


def all_fields() -> list[FieldDef]:
    """Aplana ALL_SECTIONS a una lista de FieldDef, para lookup por key."""
    return list(_FIELDS_BY_KEY.values())


def field_by_key(key: str) -> FieldDef | None:
    return _FIELDS_BY_KEY.get(key)


def resolve_origin(field: FieldDef, overrides: dict[str, Any], settings: Any) -> tuple[Any, str]:
    """Devuelve (valor_efectivo, origin) con origin en {"runtime","env","default"}.

    Tres vias, en este orden:
    1. runtime: la clave esta en `overrides` (app_config via ConfigRepo.get_all()).
    2. env: no esta en overrides pero el valor actual de Settings difiere del default
       declarado en el esquema (vino de una env var / .env).
    3. default: coincide con el default del esquema.

    Caso especial `camera_url`: el valor devuelto (en cualquiera de las tres vias)
    SIEMPRE pasa por `mask_rtsp_url()` antes de salir de esta funcion — nunca se
    devuelve la URL cruda. La mascara se aplica DESPUES de decidir `origin` sobre el
    valor sin enmascarar, para que enmascarar no afecte la comparacion `!=` contra el
    default (que tampoco lleva credenciales embebidas).
    """
    if field.key in overrides:
        value, origin = overrides[field.key], "runtime"
    else:
        current = getattr(settings, field.key, field.default)
        if current != field.default:
            value, origin = current, "env"
        else:
            value, origin = current, "default"

    if field.key == "camera_url":
        from backend.config import mask_rtsp_url
        value = mask_rtsp_url(value)

    return value, origin


def build_candidate_settings(settings: Any, overrides: dict[str, Any], changes: dict[str, Any]) -> Any:
    """Construye un Settings candidato = overrides + changes aplicados sobre defaults.

    Usa el CONSTRUCTOR completo (no `model_copy`): en pydantic 2.13.1 (instalado,
    verificado en esta sesion), `model_copy(update=...)` es una copia superficial que
    NO re-ejecuta los `model_validator(mode="after")` de `Settings`. El constructor
    si los re-ejecuta, lo que permite detectar invariantes cruzados (identidad, reid,
    behavior, object, snapshot — `backend/config.py:309-407`) sin reimplementarlos en
    el router (32-02, SET-03/D-10).

    Lanza `pydantic.ValidationError` si algun `model_validator` rechaza la combinacion.
    """
    from backend.config import Settings

    base = settings.model_dump()
    base.update(overrides)      # runtime ya persistido
    base.update(changes)        # cambios propuestos en este PUT
    return Settings(**base)     # constructor completo -> SI re-ejecuta field_validator y model_validator
