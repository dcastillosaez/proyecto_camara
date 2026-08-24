# Phase 32: Vista de cámara y configuración visual - Research

**Researched:** 2026-08-23
**Domain:** Panel de configuración runtime schema-driven (FastAPI + SQLAlchemy async + vanilla JS) sobre un pipeline de vídeo ya existente
**Confidence:** HIGH — casi todo lo relevante está verificado leyendo el código real, no supuesto. Las pocas piezas sin verificar están marcadas `[ASSUMED]` y recogidas en el Assumptions Log.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Estructura y navegación**
- D-01: Dos pestañas nuevas, "Cámara" y "Ajustes", en el mismo `role="tablist"` que construyó la Fase 31 — mismo hash-routing (`#camara`, `#ajustes/{sección}`), sin segundo mecanismo de navegación.
- D-02: La vista Cámara reutiliza el `<img id="video-feed">` / `/video_feed` que ya pinta Operaciones — no se duplica el stream MJPEG, se mueve la referencia visual. Operaciones no se toca: ningún panel se mueve, ningún id se borra.
- D-03: El árbol de secciones de Ajustes es un `role="tablist"` vertical anidado, no un componente nuevo. Dos niveles reales: 8 secciones × subsecciones como `<fieldset>` dentro de un único panel por sección — un solo diff, un solo guardado, un solo `CONFIG_CHANGED` por sección, no un panel por subsección.

**Esquema y datos**
- D-04: `GET/PUT /api/v2/config` no existe hoy y hay que crearlo. El esquema completo (`label`, `hint`, `min`/`max`/`default`, `origin`, `applies`, `secret`, `readonly`) lo decide y sirve el servidor; el cliente no mantiene copia de rangos ni traducciones de nombres de campo.
- D-05: Reutilizar `ConfigRepo` (`backend/storage/repositories.py:795`, `get`/`set`/`get_all` sobre `app_config`) como almacén de overrides — ya en producción. No crear un segundo almacén.
- D-06: Precedencia `runtime (app_config) > .env > default del código`, siguiendo el patrón ya implementado dos veces: `PUT /api/v2/detection/classes` (Fase 27) y el silenciado de alertas (Fase 30, clave `alerts.muted_rules`).

**Aplicación en caliente vs reinicio**
- D-07: Solo existen hoy tres rutas de aplicación en caliente: `CameraPipeline.set_zones()`, `set_detection_classes()` y `set_process_size()` (`backend/pipeline/manager.py:322/329/386`). El resto de los ~88 campos requiere reinicio. Esta fase **no amplía** esas rutas ni añade un botón de "Reiniciar el pipeline/servidor" — OPS-19 pide *señalizar*, no *ejecutar*.
- D-08: Guardar siempre persiste, aunque el cambio requiera reinicio. Nunca se bloquea un cambio por no poder aplicarse en caliente de inmediato.

**Guardado, validación y auditoría**
- D-09: Guardado explícito por sección (no autoguardado por campo); un `CONFIG_CHANGED` por sección guardada con el diff completo, vía `EventEngine.config_changed()` (`backend/events/engine.py:315`) — solo hay que pasarle el diff.
- D-10: El servidor valida el lote completo del PUT y devuelve todos los errores 422 a la vez, no el primero. En error, el diff pendiente no se descarta: solo se marcan las filas inválidas.
- D-11: "Restaurar valores por defecto" borra las filas de `app_config` de esa sección — no escribe los defaults del código encima — así un valor que venía de `.env` vuelve a `.env`. Confirmación por popover (patrón D-07 de la Fase 30), no `confirm()` nativo, con el recuento en el botón destructivo.

**Secretos**
- D-12: Ningún campo `secret` (credenciales RTSP, Tapo, dashboard, token de Telegram, webhook, credenciales de Google Drive, rutas de certificado SSL) sale del servidor, ni siquiera enmascarado — el esquema manda `configured: true|false` y nada más. Ninguno es editable desde esta interfaz. El `CONFIG_CHANGED` de auditoría nunca lleva valores `secret`.

**Barra de ajustes rápidos (vista Cámara, OPS-17)**
- D-13: Los 4 controles rápidos (clases detectadas, resolución de proceso, confianza de detección, umbral de severidad para subir a Drive) escriben por el mismo `PUT /api/v2/config` que el árbol. Guardan al cambiar (sin botón de guardado), con `debounce` de 600 ms en el deslizador de confianza.

### Claude's Discretion
- El endpoint `GET /api/alerts/config` (`backend/main.py:1197`) existe hoy pero está huérfano — ningún fichero de `frontend/` lo consume. Queda a discreción decidir si la nueva sección "Alertas → Canales" del árbol lo reutiliza como fuente de `telegram_configured`, lo sustituye, o lo deja intacto sin relación.
- Rangos/validación exactos para los campos donde `backend/config.py` no declare min/max explícitos hoy: derivarlos de los valores y comentarios ya existentes en el código, sin inventar límites arbitrarios.
- Orden de los planes/waves para cubrir las 8 secciones dentro de esta única fase: lo decide el planificador según dependencias reales (p. ej. `GET/PUT /api/v2/config` y el armazón del árbol antes que ninguna sección concreta).

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-16 | Vista de cámara con live view y salud en tiempo real (FPS, latencia, CPU, RAM, estado RTSP) | Los 6 datos ya se pintan hoy en Operaciones (tabla "Lo que ya existe" del UI-SPEC); solo falta la tarjeta de estado RTSP, construible sobre `CaptureHealth` (`backend/pipeline/capture.py:26`) ya expuesto por `GET /api/v2/cameras/{id}/health` (`backend/main.py:1173`). Ver Architecture Patterns → Vista Cámara. |
| OPS-17 | Ajustes rápidos de detección/grabación accesibles desde la vista de cámara | Reutiliza `PUT /api/v2/config` (mismo endpoint que el árbol, D-13); precedente de escritura directa en `PUT /api/v2/detection/classes` (`backend/api/v2/detection.py`). Ver Code Examples. |
| OPS-18 | Árbol de secciones de configuración | Esquema servidor-driven descrito en D-04; sin componente de árbol nuevo, reutiliza el patrón `role="tablist"` anidado de la Fase 31. Ver Architecture Patterns → esquema del servidor. |
| OPS-19 | Señalización hot vs. requiere-reinicio | Inventario exacto de las 3 únicas rutas hot-apply existentes (`backend/pipeline/manager.py:322/329/386`); todo lo demás es `applies: "restart_camera"` o `"restart_server"` declarado por campo en el esquema. Ver Common Pitfalls → Pitfall 1. |
| OPS-20 | Restaurar valores por defecto por sección | Requiere añadir un método `delete()` a `ConfigRepo` — no existe hoy (verificado, ver Don't Hand-Roll). Semántica: borrar filas, no sobreescribir con defaults (D-11). |
| SET-01 | Configuración persistida en BD y editable en caliente | `ConfigRepo` (`backend/storage/repositories.py:795`) ya es el almacén; "editable en caliente" se cumple solo para los 3 campos con ruta hot-apply (OPS-19 documenta el resto). |
| SET-02 | Precedencia runtime > .env > default, documentada y testeada | Dos precedentes reales: `yolo_classes` (Fase 27) y `alerts.muted_rules` (Fase 30). Patrón de test en `tests/test_detection_config_api.py`. Ver Code Examples y Common Pitfalls → Pitfall 4. |
| SET-03 | Rango validado en servidor con mensaje legible | `backend/config.py` ya tiene `field_validator`/`model_validator` con mensajes en español; el nuevo router debe reproducir esas mismas cotas para validación por-campo sin desincronizarse (Pitfall 3). |
| SET-04 | Auditoría CONFIG_CHANGED con diff | `EventEngine.config_changed()` (`backend/events/engine.py:315`) ya existe y ya se usa desde la Fase 27; solo falta pasarle el diff por sección, nunca campos `secret` (D-12). |
</phase_requirements>

## Summary

Esta fase no introduce tecnología nueva: es FastAPI + SQLAlchemy async + vanilla JS sobre patrones que el proyecto ya usa tres veces (Fases 27, 30). El trabajo real es de **diseño de esquema y de disciplina de reutilización**, no de investigación de librerías. El `32-UI-SPEC.md` (aprobado, 6/6 PASS) ya cierra casi todas las decisiones de producto; esta investigación se centra en verificar contra el código real qué existe, qué falta, y qué trampas concretas tiene construir un router de configuración de ~88 campos sobre una tabla clave-valor genérica.

Cuatro hallazgos condicionan el plan más que ninguna decisión de UI:

1. **`ConfigRepo` no tiene `delete()`.** Los tres precedentes (`get`, `set`, `get_all`) alcanzan para SET-01/SET-02, pero OPS-20 ("Restaurar valores por defecto" = borrar filas, D-11) necesita un método nuevo. Es un cambio pequeño y aditivo, pero si el planificador asume que `ConfigRepo` ya cubre todo lo que pide el UI-SPEC, se descubre tarde.
2. **La Fase 31 (de la que depende esta fase) está planificada pero no ejecutada.** `frontend/js/views/` no tiene `nav.js`, no hay `role="tablist"` en `index.html`, y no existe commit de código de la Fase 31 en el historial — solo 11 `PLAN.md` sin ejecutar. El `32-UI-SPEC.md` da por hecho que ese armazón ya existe ("hereda literalmente el mecanismo de navegación que construye la Fase 31"). Es un requisito de secuencia de ejecución, no de este documento: la Fase 31 tiene que ejecutarse (código, no solo plan) antes de que el trabajo de Fase 32 sobre `nav.js`/tablist tenga una base real sobre la que aplicar diffs.
3. **La validación por lote (SET-03/D-10) tiene que replicar invariantes cruzados que hoy viven en `model_validator` de `Settings`**, no solo rangos por campo: `identity_vote_window >= identity_min_votes`, `context_low_ratio < context_high_ratio`, `run_window_secs <= 12.0`, etc. Si el nuevo router solo valida min/max por campo aislado, un PUT puede persistir una combinación que el arranque del proceso (que sí corre esos `model_validator`) rechazaría — dejando el sistema en un estado que se persiste pero nunca arranca limpio.
4. **`GET /api/alerts/config` ya filtra un dato sensible sin querer:** devuelve `webhook_url` en crudo (`backend/main.py:1201`), pese a que el UI-SPEC clasifica la URL de webhook como campo `secret`. Si la sección "Alertas → Canales" reutiliza ese endpoint tal cual, hereda la fuga. No es un bug de esta fase — es preexistente — pero copiarlo sí lo sería.

**Primary recommendation:** construir `backend/api/v2/config.py` como agregador de un **registro de esquema declarativo** (una lista de definiciones de campo con label/hint/min/max/default/section/applies/secret, escrita a mano una vez a partir de `backend/config.py`) que resuelve `origin` consultando `ConfigRepo.get_all()` y aplica los mismos `model_validator` de `Settings` sobre el resultado combinado antes de persistir — no reinventar un motor de validación paralelo.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Esquema de configuración (label/hint/rango/origin/applies) | API / Backend | — | El cliente no puede mantener una copia sin desincronizarse (D-04); vive junto a `Settings` en el backend |
| Almacén de overrides (`app_config`) | Database / Storage | API / Backend | `ConfigRepo` ya envuelve el acceso; el router solo orquesta |
| Precedencia runtime > .env > default | API / Backend | — | Se resuelve en el momento de servir el `GET`, comparando `ConfigRepo.get_all()` contra `Settings` cacheada |
| Validación de rangos y de invariantes cruzados | API / Backend | — | Autoritativa en servidor (SET-03); el cliente solo refleja el 422, no lo calcula |
| Aplicación en caliente (3 rutas existentes) | API / Backend | — | `CameraPipeline` vive en el proceso backend; el cliente solo lee `applies` |
| Árbol de secciones / render de ~88 filas | Browser / Client | — | Pintado 100% en JS desde el esquema que sirve el servidor; cero HTML estático nuevo |
| Live view + teselas de métrica | Browser / Client | API / Backend (fuente de datos) | El vídeo ya es un stream servido por `StreamingWorker`; las teselas leen `/api/health` y `/api/v2/metrics` ya existentes |
| Auditoría `CONFIG_CHANGED` | API / Backend | Database / Storage | `EventEngine.config_changed()` ya publica al bus, que ya persiste en `events` |
| Enmascarado de secretos | API / Backend | — | El servidor nunca serializa el valor; es la única capa de confianza (D-12) |

## Standard Stack

Sin dependencias nuevas. Se reutiliza el stack ya fijado por `CLAUDE.md`.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | ya en requirements | Router `/api/v2/config` | Mismo patrón que `alerts.py`/`detection.py` |
| pydantic / pydantic-settings | ya en requirements | `Settings` (fuente de defaults/rangos) + `BaseModel` del payload del PUT | Ya es la fuente de verdad de `backend/config.py` |
| SQLAlchemy 2 async + aiosqlite | ya en requirements | `ConfigRepo` sobre `app_config` | Reutilizado tal cual, D-05 |
| slowapi | ya en requirements | Rate limit del router nuevo (`V2_RATE_LIMIT`, `backend/api/v2/deps.py:26`) | Mismo límite compartido que el resto de `/api/v2` |

### Supporting
Ninguna. Frontend es HTML/CSS/JS vanilla con Tailwind CDN — cero librerías de formularios, validación de esquema en cliente, o componente de árbol (fijado por `32-UI-SPEC.md` §"Design System").

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Esquema declarativo a mano en `config.py`/`config_schema.py` | Generar el esquema por introspección de `Settings.model_fields` con `Field(json_schema_extra=...)` | La introspección automática evitaría duplicar los ~88 nombres, pero pydantic-settings no tiene hoy un lugar natural para `section`/`hint`/`applies` sin ensuciar `Settings` con metadatos de UI; y las cotas de `model_validator` (cruzadas entre campos) no son extraíbles por introspección de todas formas. Un módulo de esquema explícito es más código pero cero magia — y es coherente con "sin dependencias nuevas" |
| `ConfigRepo.delete(key)` por campo | Un método `delete_prefix()`/`clear_section()` que requeriría prefijar las claves de `app_config` (`"deteccion.yolo_confidence"`) | Los dos precedentes (`yolo_classes`, `alerts.muted_rules`) usan claves planas sin prefijo. Prefijar rompería la compatibilidad con esas dos filas ya en producción. Mejor: `delete(key)` por campo, y que "restaurar sección" itere los `field.key` de esa sección del esquema y borre los que existan — la sección es un concepto del esquema, no del almacén |

**Installation:** ninguna — no hay paquetes nuevos que instalar.

**Version verification:** no aplica; no se añade ninguna dependencia con versión propia.

## Architecture Patterns

### System Architecture Diagram

```
Navegador                          Backend (FastAPI)                    Almacenamiento
──────────                         ──────────────────                   ──────────────

GET /api/v2/config  ─────────────► config.py (router)
                                     │
                                     ├─► ConfigRepo.get_all()  ─────────► app_config (SQLite)
                                     │      (overrides runtime)
                                     ├─► Settings (get_settings(),        .env (leído al arrancar,
                                     │      cacheada @lru_cache)           cacheado en Settings)
                                     └─► FIELD_SCHEMA (módulo Python,
                                            label/hint/min/max/default/
                                            section/applies/secret)
                                     │
                                     ▼
                              resolver por campo:
                                origin = "runtime" si está en app_config
                                       = "env"     si Settings != default Y no está en app_config
                                       = "default" si coincide con el default de Settings
                                secret → value=None, configured=bool(valor no vacío)
                                     │
                                     ▼
                           { sections: [{ key, label, groups: [{ fields: [...] }] }] }
                                     │
                                     ▼
◄──────────────────────────────────┘
frontend/js/views/settings.js
  → pinta árbol + filas desde el esquema (cero HTML estático)


PUT /api/v2/config  ─────────────► config.py (router)
  { section: "deteccion",              │
    changes: {yolo_confidence: 0.5} }  ├─► valida cada campo contra
                                        │    FIELD_SCHEMA[key].min/max/type
                                        ├─► reconstruye un Settings candidato
                                        │    (valores actuales + cambios) y
                                        │    corre los model_validator de
                                        │    Settings sobre él (invariantes
                                        │    cruzados, sin tocar el singleton)
                                        │
                                   422 con todos los errores ◄── si falla
                                        │
                                        ├─► ConfigRepo.set(key, value)  ───► app_config
                                        │    por cada campo válido
                                        ├─► si key en {yolo_classes,
                                        │    process_width/height, zones}:
                                        │    CameraPipeline.set_*() (hot-apply)
                                        └─► EventEngine.config_changed(
                                              now, section=..., diff={...})
                                                  │
                                                  ▼
                                             events (SQLite) + WebSocket
```

### Recommended Project Structure
```
backend/
  api/v2/
    config.py              # nuevo — GET/PUT /api/v2/config
    config_schema.py        # nuevo — FIELD_SCHEMA declarativo (~88 entradas, 8 secciones)
  storage/
    repositories.py         # ConfigRepo += delete(key)
frontend/
  js/
    views/
      camera.js             # nuevo — orquestador vista Cámara
      camera-quick.js        # nuevo — barra de ajustes rápidos
      settings.js             # nuevo — orquestador vista Ajustes (esquema, árbol, deep-link)
      settings-section.js      # nuevo — pintado de una sección (fieldsets + filas)
      settings-field.js         # nuevo — un control por tipo + badges + error
      settings-save.js           # nuevo — diff, PUT, mapeo 422→filas, restaurar
    nav.js                  # de la Fase 31 — se EXTIENDE, no se reescribe (+2 entradas)
  css/
    components.css          # += .cfg-tree .cfg-node .cfg-row .cfg-badge .cfg-applies
                             #    .cfg-savebar .metric-tile .rtsp-card
tests/
  test_config_api.py        # nuevo — GET/PUT, 422 batch, precedencia, restaurar, CONFIG_CHANGED
```

### Pattern 1: Esquema servidor-driven, sin copia en cliente
**What:** El backend sirve un JSON con toda la metadata de presentación (label, hint, rango, default, origin, applies, secret) por campo; el cliente solo renderiza, nunca decide un rango o una traducción.
**When to use:** Siempre que SET-02/SET-03 dependan de una única fuente de verdad — es la decisión D-04, no una alternativa a evaluar.
**Example:**
```python
# Source: patrón derivado de backend/api/v2/detection.py (Fase 27), verificado en el repo
@dataclass(frozen=True)
class FieldDef:
    key: str            # nombre exacto en Settings, y clave en app_config
    env: str             # nombre de la env var (mayúsculas)
    label: str
    hint: str
    type: str            # "bool" | "int" | "float" | "enum" | "time" | "list_int" | "secret" | "readonly"
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    enum_values: tuple[str, ...] | None = None
    applies: str = "restart_camera"   # "hot" | "restart_camera" | "restart_server"
    secret: bool = False
    readonly: bool = False

DETECCION_PERSONAS: tuple[FieldDef, ...] = (
    FieldDef(
        key="yolo_confidence", env="YOLO_CONFIDENCE",
        label="Confianza mínima de detección",
        hint="Por debajo de este valor YOLO descarta la detección.",
        type="float", default=0.45, min=0.05, max=0.95, step=0.05,
        applies="hot",   # ver Pitfall 1 — NO ESTÁ en las 3 rutas hot-apply hoy;
                         # confirmar con el planificador antes de marcarlo "hot"
    ),
)
```

### Pattern 2: Resolución de `origin` sin tercer almacén
**What:** `origin` se calcula en el momento del `GET`, comparando tres fuentes ya existentes — nunca se persiste como columna aparte.
**When to use:** Para cada campo del esquema.
**Example:**
```python
# Source: patrón derivado de backend/api/v2/detection.py:79-81 (Fase 27), get_classes()
overrides = await _config_repo().get_all()   # dict completo, una sola consulta
settings = get_settings()

def resolve_origin(field: FieldDef, settings: Settings) -> tuple[Any, str]:
    if field.key in overrides:
        return overrides[field.key], "runtime"
    current = getattr(settings, field.key)
    if current != field.default:
        return current, "env"
    return current, "default"
```

### Pattern 3: Validación por lote reutilizando `Settings.model_validator`
**What:** En vez de reimplementar `identity_vote_window >= identity_min_votes` y las demás cotas cruzadas dentro del router, construir un `Settings` candidato con los valores actuales + los cambios propuestos y dejar que sus propios `model_validator` (ya en `backend/config.py:309-407`) lo rechacen.
**When to use:** SET-03, específicamente para invariantes que cruzan más de un campo (no basta min/max por campo).
**Example:**
```python
# Source: patrón derivado de backend/config.py — Settings ya valida esto al arrancar
try:
    candidate = get_settings().model_copy(update=changes)
    Settings.model_validate(candidate.model_dump())  # re-corre los @model_validator
except ValidationError as e:
    # mapear cada error de pydantic a la fila correspondiente (loc[0] == field key)
    ...
```
Nota: verificar en implementación que `model_copy(update=...)` efectivamente re-ejecuta los `model_validator(mode="after")` — en pydantic v2 `model_copy` **no** re-valida por defecto; puede hacer falta `Settings(**{**current.model_dump(), **changes})` (constructor completo) en su lugar para forzar la validación. Confirmar contra la versión de pydantic instalada antes de fijar el patrón en el plan.

### Anti-Patterns to Avoid
- **Prefijar las claves de `app_config` por sección** (`"deteccion.yolo_confidence"`): rompe la compatibilidad con las dos filas ya en producción (`yolo_classes`, `alerts.muted_rules`), que usan claves planas. La sección es un concepto del esquema (agrupación de `FieldDef`), no del almacén.
- **Copiar `GET /api/alerts/config` tal cual para la sección Alertas → Canales**: ese endpoint devuelve `webhook_url` sin enmascarar (`backend/main.py:1201`), contradiciendo D-12. Si se reutiliza, hay que envolverlo o corregirlo, no importarlo directo.
- **Validar solo min/max por campo en el PUT**: deja pasar combinaciones que el arranque del proceso rechazaría (ver Pattern 3). El batch tiene que validar también los `model_validator` cruzados.
- **Un segundo intervalo de refresco para las teselas de la vista Cámara**: el UI-SPEC ya fija que se reutiliza el tick de 5 s de `dashboard-observability.js`; crear un segundo timer duplicaría peticiones a `/api/health` y `/api/v2/metrics` sin ganar nada perceptible.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Almacén clave-valor de configuración runtime | Una tabla nueva o un fichero JSON de overrides | `ConfigRepo` (`backend/storage/repositories.py:795`) | Ya en producción, ya usado por dos fases; añadir un segundo almacén rompería SET-02 |
| Emisión de evento de auditoría de configuración | Un publisher nuevo hacia el bus de eventos | `EventEngine.config_changed()` (`backend/events/engine.py:315`) | Ya emite `EventType.CONFIG_CHANGED` (catálogo desde Fase 19); solo falta pasarle `detail` |
| Validación de invariantes cruzados entre campos de config | Un validador ad hoc por sección en el router | Los `model_validator(mode="after")` ya escritos en `backend/config.py` (identidad, ReID, behavior, object, snapshot) | Reescribirlos en el router duplica lógica que ya existe y puede desincronizarse silenciosamente del arranque real del proceso |
| Confirmación destructiva de "Restaurar valores por defecto" | Un modal nuevo o `confirm()` nativo | El patrón de popover de silenciado (D-07, Fase 30, `alertCenter.js`) | Mismo componente visual y de accesibilidad ya verificado por checker en la Fase 30 |
| Chips de clases COCO conmutables (ajustes rápidos, sección Detección) | Un componente de chips nuevo | `components/detectionClasses.js` de la Fase 27 | Ya renderiza exactamente ese control con `aria-pressed` |
| Enmascarado de la URL RTSP | Lógica de regex en el cliente | `mask_rtsp_url()` (`backend/config.py:429`) | Ya existe, ya se usa para logging; la UI solo debe pedirla ya enmascarada al servidor, nunca construirla en el navegador |

**Key insight:** Todo lo "difícil" de esta fase (almacén, auditoría, validación cruzada, confirmación destructiva, chips) ya tiene una implementación en el repo. El trabajo nuevo real es small: un `delete()` en `ConfigRepo`, un módulo de esquema declarativo, y el router que los conecta.

## Common Pitfalls

### Pitfall 1: Marcar un campo como `applies: "hot"` sin verificar que existe la ruta real
**What goes wrong:** El esquema declara `applies` libremente por campo; es tentador marcar como "hot" cualquier campo que "debería" poder cambiar en caliente (p. ej. `yolo_confidence`, que técnicamente el detector podría leer en cada frame).
**Why it happens:** El detector sí lee `self._classes` en caliente para clases (Fase 27), lo que puede sugerir por analogía que otros parámetros del mismo detector también son hot — pero `set_detection_classes()` es una ruta explícita y `yolo_confidence` no tiene ninguna equivalente hoy.
**How to avoid:** `applies` solo puede ser `"hot"` para los tres campos con una llamada real: clases (`set_detection_classes`), `process_width`/`process_height` (`set_process_size`), y zonas (`set_zones`, fuera del árbol — es UI de la Fase 27/29). Todo lo demás es `"restart_camera"` o `"restart_server"` según si el campo lo consume `CameraPipeline` o el proceso completo (p. ej. `host`/`port`/`ssl_*` son `"restart_server"`).
**Warning signs:** Un test que guarda un campo marcado "hot" y comprueba que el pipeline realmente cambió de comportamiento sin reiniciar — si ese test no existe para un campo "hot", es sospechoso.

### Pitfall 2: `ConfigRepo.delete()` no existe — bloquea OPS-20 si no se añade primero
**What goes wrong:** El plan asume "restaurar sección" es solo borrar filas de `app_config`, pero `ConfigRepo` (verificado, `backend/storage/repositories.py:795-818`) solo tiene `get`, `set`, `get_all`. Sin `delete()`, OPS-20 no tiene cómo implementarse sin tocar SQLAlchemy directamente desde el router (rompiendo el patrón de reutilización de D-05).
**Why it happens:** Los dos precedentes de `ConfigRepo` (Fase 27, Fase 30) solo escriben y leen, nunca borran — nadie necesitó "deshacer" hasta ahora.
**How to avoid:** Añadir `async def delete(self, key: str) -> bool` a `ConfigRepo` en el mismo plan que introduce el router (no como parche posterior). "Restaurar sección" itera los `field.key` de esa sección en `FIELD_SCHEMA` y llama `delete()` por cada uno presente en `app_config`.
**Warning signs:** Un plan que dice "usar `ConfigRepo` tal cual" para OPS-20 sin mencionar un método nuevo.

### Pitfall 3: Duplicar los rangos de `backend/config.py` en el router en vez de derivarlos
**What goes wrong:** Escribir min/max a mano en `FIELD_SCHEMA` sin mirar los `field_validator`/`model_validator` reales puede introducir un rango distinto al que `Settings` aplicaría al arrancar — un valor que el 422 acepta pero que el proceso rechazaría en el próximo reinicio (contradice D-08, "guardar siempre persiste... la próxima vez que arranque sí valdrá").
**Why it happens:** No todos los campos tienen rango explícito en `config.py` (p. ej. `recording_fps`, `pre_buffer_max_mb` no tienen validador); el investigador/planificador tiene que inventar un rango razonable para esos (discreción explícita del CONTEXT), pero para los que **sí** tienen validador (identidad, ReID, behavior, object, snapshot — ver `backend/config.py:309-407`), el rango del esquema debe coincidir exactamente.
**How to avoid:** Al construir `FIELD_SCHEMA`, para cada campo con `field_validator`/`model_validator` existente, citar la línea de `config.py` como fuente del rango — no inventar un segundo número.
**Warning signs:** Un test que guarda un valor válido según el esquema del router pero que `Settings()` rechazaría al arrancar con ese mismo valor en `.env`.

### Pitfall 4: Precedencia inconsistente entre `list`/`dict` y escalares
**What goes wrong:** `yolo_classes` (`list[int]`), `object_class_ids` (`list[int]`), `schedule_days` (`list[int]`), `cors_origins` (`list[str]`) se comparan con `!=` para decidir `origin` (Pattern 2); comparar listas por igualdad de contenido funciona en Python, pero si `app_config.value` se guarda como JSON y vuelve deserializado con un orden distinto (no debería pasar con SQLite JSON estándar, pero conviene no asumirlo sin probarlo), la comparación `current != field.default` podría dar falsos "env" cuando en realidad es "default".
**Why it happens:** El resto de precedentes (`yolo_classes`) solo compara `app_config` vs. ausencia, nunca compara profundamente contra el default de `Settings` para decidir `"env"` vs `"default"` — este endpoint es el primero que necesita esa comparación de tres vías.
**How to avoid:** Test explícito: un campo `list[int]` con `.env` distinto del default debe resolver `origin="env"`, y con `.env` ausente debe resolver `origin="default"`, verificando literalmente el JSON ida y vuelta contra SQLite.
**Warning signs:** Un campo de tipo lista que siempre muestra `origin="env"` aunque `.env` no lo declare.

### Pitfall 5: Bloquear la ejecución de esta fase por asumir que la Fase 31 ya está en código
**What goes wrong:** El `32-UI-SPEC.md` da por hecho `nav.js`, `role="tablist"` y el hash-routing de la Fase 31 como si ya existieran (los cita con líneas y comportamiento concreto). Verificado en el repo: no existen todavía — la Fase 31 solo tiene 11 `PLAN.md` sin ejecutar (`.planning/phases/31-vista-de-anal-tica/`), cero commits de código.
**Why it happens:** El UI-SPEC de la Fase 32 se escribió asumiendo que la Fase 31 se ejecutaría antes, que es el orden natural del roadmap — pero "planificado" y "ejecutado" no son lo mismo, y el research de la Fase 32 se hizo en paralelo al final de la planificación de la 31.
**How to avoid:** El plan de la Fase 32 debe declarar explícitamente la dependencia de ejecución (no solo de planificación) sobre la Fase 31, y el primer wave de la Fase 32 no puede tocar `nav.js` hasta confirmar que existe en el árbol de trabajo.
**Warning signs:** Un plan de Fase 32 que dice "extender `nav.js`" sin haber comprobado antes que el fichero existe.

### Pitfall 6: Presupuesto de líneas de `components.css` ya ajustado antes de empezar
**What goes wrong:** `frontend/css/components.css` mide hoy 163 líneas (verificado) contra un tope duro de 300 (`tests/test_frontend_modules.py::TEST_line_limit`). El UI-SPEC de la Fase 32 promete añadir 8 clases nuevas (`.cfg-tree`, `.cfg-node`, `.cfg-row`, `.cfg-badge`, `.cfg-applies`, `.cfg-savebar`, `.metric-tile`, `.rtsp-card`) al mismo fichero — y la Fase 31, que se ejecutará antes, también va a añadir sus propias clases al mismo fichero compartido, consumiendo presupuesto que hoy no se puede medir con precisión porque su código no existe todavía.
**Why it happens:** `components.css` es un único fichero compartido por todas las vistas (Fase 28: `LOCKED_CSS = ["base.css", "layout.css", "components.css"]`), y dos fases consecutivas escriben en él sin coordinación explícita de presupuesto.
**How to avoid:** Antes de escribir las clases de la Fase 32, medir `wc -l frontend/css/components.css` con el código de la Fase 31 ya fusionado. Si el margen es insuficiente, la salida documentada por el propio proyecto (precedente Fase 30: mover código a un módulo nuevo para "recuperar margen") es añadir un fichero CSS nuevo y sumarlo a `LOCKED_CSS` — una decisión mecánica y explícita, no un ajuste silencioso.
**Warning signs:** `TEST_line_limit` fallando después de un plan que "solo añadía CSS".

## Code Examples

### Router existente que sirve de molde exacto (Fase 27)
```python
# Source: backend/api/v2/detection.py (leído completo en esta investigación)
router = APIRouter(prefix="/api/v2/detection", tags=["detection"])

_camera_manager: Any = None
_event_engine: Any = None

def configure(camera_manager: Any, event_engine: Any = None) -> None:
    """Wire the live CameraManager/EventEngine instances. Called once from main.py's lifespan."""
    global _camera_manager, _event_engine
    _camera_manager = camera_manager
    _event_engine = event_engine

def _config_repo() -> ConfigRepo:
    return ConfigRepo(get_session_factory())

@router.put("/classes")
@limiter.limit(V2_RATE_LIMIT)
async def put_classes(request: Request, body: DetectionClassesIn) -> dict[str, Any]:
    # ... validar ...
    await _config_repo().set(CONFIG_KEY, list(ids))          # persistir ANTES de propagar
    if _camera_manager is not None:
        for pipeline in _camera_manager.all():
            pipeline.set_detection_classes(list(ids))          # hot-apply
    if _event_engine is not None:
        _event_engine.config_changed(datetime.datetime.now(), classes=list(ids))  # auditoría
    return _classes_payload(list(ids))
```
El router `config.py` de esta fase sigue el mismo molde: `configure()` inyectado desde `main.py` en el lifespan (línea ~590 hoy), `_config_repo()` como fábrica parcheable en tests (igual que hace `tests/test_detection_config_api.py`), y "persistir antes de propagar".

### Precedente de auditoría con diff (Fase 30, `alerts.py`)
```python
# Source: backend/api/v2/alerts.py — patrón MUTED_KEY / read-modify-write serializado
_mute_lock = asyncio.Lock()   # serializa el read-modify-write de app_config

async def _load_muted(now): ...
```
Para el PUT de configuración de esta fase, un lock de módulo equivalente evita una condición de carrera si dos operadores guardan la misma sección casi a la vez — el patrón ya existe, solo se replica.

### Registro del router en `main.py`
```python
# Source: backend/main.py (patrón de las líneas 590-772, verificado)
config_v2_module.configure(camera_manager, event_engine)   # junto a detection_v2_module.configure
...
app.include_router(config_v2_router)
```

## State of the Art

No aplica una tabla "old vs new" — esta fase no reemplaza ningún mecanismo previo del proyecto, añade el primer editor de configuración runtime completo sobre patrones ya vigentes desde la Fase 27.

**Deprecated/outdated:** ninguno. `GET /api/alerts/config` (Fase 12, huérfano) no se deprecia formalmente por esta investigación — queda a discreción del planificador si se sustituye o se deja intacto (ver `<decisions>` → Claude's Discretion).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `model_copy(update=...)` de pydantic v2 podría no re-ejecutar `model_validator(mode="after")`, y haría falta construir `Settings(**dict_completo)` en su lugar | Architecture Patterns → Pattern 3 | Si el plan asume `model_copy` valida y en realidad no lo hace, el PUT aceptaría combinaciones inválidas que el arranque real rechazaría — mismo riesgo que Pitfall 3, pero por mecanismo distinto. Verificar contra `pydantic` instalado (`pip show pydantic`) antes de fijar el patrón en el plan |
| A2 | Los campos sin `field_validator`/`model_validator` explícito en `config.py` (p. ej. `recording_fps`, `pre_buffer_max_mb`, `local_retention_days`) necesitan un rango inventado razonablemente para el esquema, ya que el CONTEXT delega esto al investigador/planificador sin fijar valores | Standard Stack / Pattern 1 | Bajo — es discreción explícita del usuario (CONTEXT §Claude's Discretion), no una afirmación fáctica sobre el sistema. Riesgo solo si el rango elegido es tan estrecho que bloquea un valor operativo legítimo |
| A3 | El agrupamiento de los ~88 campos en las 8 secciones × subsecciones de la tabla del UI-SPEC (Cámara/Detección/Tracking/Reconocimiento/Zonas/Reglas/Alertas/Almacenamiento) es coherente con los bloques de comentarios ya existentes en `backend/config.py` (p. ej. "--- Identidad temporal (Fase 24) ---"), pero no se verificó campo por campo que los ~88 caigan exactamente en esa partición sin solapes ni huecos | Architecture Patterns → Recommended Project Structure | Medio — si algún campo no encaja limpiamente en una sección (p. ej. `gallery_throttle_secs`, que no tiene bloque de comentario propio), el planificador tiene que decidir dónde va sin que esta investigación lo haya resuelto |

## Open Questions (RESOLVED)

1. **¿La Fase 31 debe ejecutarse (código real, no solo planes) antes de que arranque la ejecución de la Fase 32?**
   - What we know: El `32-UI-SPEC.md` asume literalmente el armazón de navegación de la Fase 31 (`nav.js`, `role="tablist"`, hash-routing); verificado que ese código no existe hoy en el árbol de trabajo, solo 11 `PLAN.md` sin ejecutar.
   - What's unclear: Si el orquestador de fases fuerza la ejecución secuencial (Fase 31 antes que 32) o si es responsabilidad del usuario/operador confirmarlo antes de lanzar `/gsd:plan-phase 32` en modo ejecución.
   - Recommendation: El plan de la Fase 32 debe incluir, como primer paso de su primer wave, una verificación explícita de que `frontend/js/nav.js` existe y expone la superficie que el UI-SPEC da por hecha — fallar rápido y explícito si no, en vez de que la Fase 32 reescriba silenciosamente su propia versión de navegación.
   - **RESOLVED:** `32-01` Task 0 hace la verificación temprana y no bloqueante (deja constancia en el SUMMARY sin detener el wave, porque 32-01..32-06 no dependen del tablist). `32-07` Task 1 —el único plan que toca `nav.js`— sí bloquea de forma dura si `frontend/js/nav.js` sigue sin existir, y detiene la ejecución con instrucciones explícitas de lanzar `/gsd-execute-phase 31` primero, sin construir un tablist sustituto.

2. **¿Se reutiliza, sustituye o se deja intacto `GET /api/alerts/config`?**
   - What we know: Existe, está huérfano, y filtra `webhook_url` sin enmascarar (contradice D-12 si se reutiliza tal cual para la sección Alertas → Canales).
   - What's unclear: El CONTEXT lo deja explícitamente a discreción del planificador — no es una decisión de producto del usuario.
   - Recommendation: Si se reutiliza como fuente de `telegram_configured`, envolver el resultado y quitar `webhook_url` en crudo de lo que llega al navegador; si se deja intacto, la nueva sección "Alertas" del árbol no debe apuntar a él y debe leer todo desde el nuevo `GET /api/v2/config`.
   - **RESOLVED:** Ningún plan (32-01..32-08) referencia `/api/alerts/config` — la sección "Alertas → Canales" del árbol se sirve íntegramente desde el nuevo `GET /api/v2/config`, dejando el endpoint huérfano intacto y sin relación, tal y como recomendaba la segunda opción.

3. **¿Cómo se representan en el esquema los campos de solo lectura calculados (p. ej. "Zonas definidas", "Reglas cargadas"), que no viven en `Settings` sino en tablas `zones`/`rules`?**
   - What we know: El UI-SPEC dice que las subsecciones "Zonas definidas" y "Reglas cargadas" son de solo lectura dentro del árbol de Ajustes, con su propio empty state ("Las zonas se crean... desde el panel «Zonas de interés» de Operaciones").
   - What's unclear: Si esas filas de solo lectura viven en el mismo esquema `GET /api/v2/config` (mezclando `Settings`-backed y BD-backed en la misma respuesta) o si el frontend hace una consulta aparte a los endpoints ya existentes de zonas/reglas y las inyecta visualmente en el árbol.
   - Recommendation: Mantenerlas fuera del esquema de `Settings` — consultar los endpoints ya existentes (zonas/reglas) desde `settings-section.js` cuando el usuario entra en esas subsecciones, evitando que el router de config tenga que conocer tablas que no le pertenecen.
   - **RESOLVED:** `32-01` Task 2 marca esas filas con `external_source="/api/zones"` / `external_source="/api/v2/rules"` en vez de incluirlas como campos `Settings`-backed — el router de config no consulta esas tablas.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`pytest.ini`: `python_functions = TEST_*`, `asyncio_mode = auto`) |
| Config file | `pytest.ini` (raíz del proyecto) |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/test_config_api.py -q` (fichero nuevo, ver Wave 0) |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -q` |

No hay Playwright ni ningún test runner de frontend instalado (`TEST-02` es v2 pendiente, fuera de esta fase); la verificación visual sigue el patrón de checkpoint manual ya usado en las Fases 29/30/31.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-16 | `GET /api/v2/cameras/{id}/health` ya expone lo necesario para la tarjeta RTSP | unit | `pytest tests/test_pipeline_v2.py -k health -x` | ✅ (endpoint y `CaptureHealth` ya cubiertos por tests existentes de la Fase 17) |
| OPS-17 | Los 4 controles rápidos escriben por `PUT /api/v2/config` | integration | `pytest tests/test_config_api.py -k quick_settings -x` | ❌ Wave 0 |
| OPS-18 | `GET /api/v2/config` devuelve las 8 secciones con label/hint/rango/origin/applies | unit | `pytest tests/test_config_api.py -k get_config_schema -x` | ❌ Wave 0 |
| OPS-19 | Cada campo del esquema declara `applies` coherente con las 3 rutas hot-apply reales | unit | `pytest tests/test_config_api.py -k applies_matches_hot_apply_routes -x` | ❌ Wave 0 |
| OPS-20 | Restaurar sección borra solo las filas `runtime` de esa sección, deja `.env`/default intactos | integration | `pytest tests/test_config_api.py -k restore_section -x` | ❌ Wave 0 |
| SET-01 | Un campo editado persiste en `app_config` y sobrevive a un reinicio simulado (`get_settings.cache_clear()`) | integration | `pytest tests/test_config_api.py -k persists_across_restart -x` | ❌ Wave 0 |
| SET-02 | Precedencia runtime > .env > default, con los tres estados de `origin` verificados | unit | `pytest tests/test_config_api.py -k precedence -x` | ❌ Wave 0 |
| SET-03 | 422 legible con todos los errores del lote, no solo el primero; invariante cruzado (p. ej. `identity_vote_window < identity_min_votes`) también rechazado | unit | `pytest tests/test_config_api.py -k batch_validation_errors -x` | ❌ Wave 0 |
| SET-04 | `PUT` exitoso emite un único `CONFIG_CHANGED` con el diff completo de la sección, nunca con campos `secret` | unit | `pytest tests/test_config_api.py -k config_changed_emits_diff -x` | ❌ Wave 0 |
| D-12 (secretos) | Un campo `secret` nunca aparece en el JSON del `GET`, ni en el diff del evento | unit | `pytest tests/test_config_api.py -k secret_never_leaves_server -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_config_api.py -q`
- **Per wave merge:** `pytest tests/ -q` (suite completa — este proyecto exige "suite completa si toca... API o configuración", `CLAUDE.md` §Tests)
- **Phase gate:** Full suite green before `/gsd-verify-work`, más el checkpoint visual manual (patrón de las Fases 29-31) para OPS-16/17/18/20 — el UI-SPEC ya fija los criterios exactos a verificar con navegador real.

### Wave 0 Gaps
- [ ] `tests/test_config_api.py` — cubre OPS-17..20, SET-01..04, D-12 (nuevo, molde: `tests/test_detection_config_api.py`)
- [ ] `backend/storage/repositories.py::ConfigRepo.delete()` — no es un test, es un método faltante que el Wave 0 de tests va a necesitar como fixture/mock antes de que exista el código real (mismo patrón que `tests/test_detection_config_api.py` parchea `_config_repo`)
- [ ] Framework install: ninguno — pytest ya está instalado y configurado

*(Todo lo demás — framework, fixtures compartidas, patrón de cliente HTTP — ya existe y se reutiliza de `tests/test_detection_config_api.py` y `tests/conftest.py`)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (sin cambios) | Auth global Basic Auth todo-o-nada ya aplicada a nivel de app (`FastAPI(dependencies=[Depends(verify)])`); el router nuevo la hereda automáticamente, igual que el resto de `/api/v2` |
| V3 Session Management | no aplica | Sin sesiones — Basic Auth stateless, sin cambios de esta fase |
| V4 Access Control | sí | Sin roles en el sistema (documentado en `backend/api/v2/detection.py` docstring): cualquier credencial válida puede editar toda la configuración. La única mitigación es auditoría (`CONFIG_CHANGED` por sección, D-09) y rate limit compartido (`V2_RATE_LIMIT`, `backend/api/v2/deps.py:26`) |
| V5 Input Validation | sí | `pydantic` (`BaseModel` del payload PUT) + los `field_validator`/`model_validator` ya existentes en `Settings`, reutilizados vía Pattern 3 — no un validador nuevo y paralelo |
| V6 Cryptography | no aplica | Ningún campo de esta fase maneja criptografía nueva; los secretos existentes (RTSP, Tapo, dashboard, Telegram, webhook, Drive, SSL) se tratan como opacos (V2.10-equivalente: nunca se leen, nunca se escriben desde aquí) |

### Known Threat Patterns for este stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Fuga de credenciales/tokens vía el esquema de configuración (p. ej. devolver `rtsp_pass` o `alert_telegram_token` en el JSON del `GET`) | Information Disclosure | El esquema marca `secret: true` por campo y el router **nunca** serializa `getattr(settings, field.key)` para esos campos — solo `configured: bool(valor)`. Verificado como riesgo real: `GET /api/alerts/config` (huérfano, Fase 12) ya comete este error con `webhook_url` — no replicarlo (Anti-Patterns) |
| Escalado de privilegio implícito: cualquier usuario autenticado puede cambiar `dashboard_user`/`dashboard_pass` o `ssl_certfile`/`ssl_keyfile` si esos campos se marcan editables por error | Elevation of Privilege | Esos campos van marcados `secret: true` y/o `readonly: true` en `FIELD_SCHEMA` — nunca aceptan un PUT. El test `secret_never_leaves_server` (Wave 0) debe cubrir también que un PUT contra un campo `secret` devuelve 4xx, no un 200 silencioso |
| Inyección de un rango inválido que rompe el arranque del proceso (config runtime que pasa el 422 del router pero que `Settings()` rechazaría al reiniciar) | Tampering | Pattern 3 — reutilizar los `model_validator` de `Settings` en el batch del PUT, no un validador paralelo desincronizado |
| Denegación de servicio por PUT masivo repetido (88 campos, sin límite de tamaño de payload) | Denial of Service | Rate limit ya compartido (`@limiter.limit(V2_RATE_LIMIT)`, 60/min); el payload máximo es acotado por el propio número de campos del esquema (no hay listas de longitud arbitraria excepto `cors_origins`/`object_class_ids`/`schedule_days`, ya validadas por `Settings`) |
| XSS almacenado vía `label`/`hint` del esquema si algún campo llegara a aceptar texto libre reflejado sin escapar | Tampering / Information Disclosure | La convención anti-XSS del proyecto (heredada, `32-UI-SPEC.md` §"Convención anti-XSS") ya exige `textContent`/`dataset` para todo dato de servidor en `settings-field.js`; ningún campo de este esquema acepta texto libre del usuario que luego se re-sirva sin pasar por `Settings` |

## Sources

### Primary (HIGH confidence — código leído directamente en esta sesión)
- `backend/config.py` — `Settings` completo, todos los `field_validator`/`model_validator`, ~88 campos confirmados por lectura íntegra
- `backend/storage/repositories.py:795-818` — `ConfigRepo` (get/set/get_all, sin delete)
- `backend/storage/models.py:199-204` — `AppConfig` (tabla `app_config`, columna `value` tipo `JSON`)
- `backend/events/engine.py:315-324` — `EventEngine.config_changed()`
- `backend/events/types.py:45` — `EventType.CONFIG_CHANGED` en el catálogo
- `backend/api/v2/detection.py` — router completo (molde de referencia)
- `backend/api/v2/alerts.py` — patrón de `_mute_lock`, `MUTED_KEY`, read-modify-write
- `backend/api/v2/deps.py` — `limiter`, `V2_RATE_LIMIT`, `pagination_limit`, `snapshot_url`
- `backend/pipeline/manager.py:322,329,386` — `set_zones`/`set_detection_classes`/`set_process_size` (únicas 3 rutas hot-apply)
- `backend/pipeline/capture.py:26-36` — `CaptureHealth`
- `backend/main.py:1159-1210` — `/api/v2/cameras`, `/api/v2/cameras/{id}/health`, `GET /api/alerts/config` (con la fuga de `webhook_url` verificada)
- `backend/main.py:424,587,590,593,753-772` — patrón `configure()` + `include_router()` en el lifespan
- `tests/test_detection_config_api.py` — patrón de test para el router nuevo
- `tests/test_frontend_modules.py` — `LOCKED_JS`, `LOCKED_CSS`, `LINE_LIMIT=300`, `TEST_no_inline_logic`
- `frontend/js/app.js` — orden de wiring actual, punto de inserción para `initCamera()`/`initSettings()`
- `frontend/js/views/dashboard-observability.js` — patrón exacto del tick de 5 s a reutilizar
- `frontend/index.html` (grep) — confirma ausencia actual de `role="tablist"`
- `frontend/js/`, `frontend/css/components.css` (163 líneas medidas) — estado real del árbol de trabajo
- `.planning/phases/31-vista-de-anal-tica/` (listado) — 11 `PLAN.md` + CONTEXT/RESEARCH/UI-SPEC/VALIDATION, cero código ejecutado (confirmado por `git log` sin commits de Fase 31)
- `.planning/config.json` — `nyquist_validation: true`, sin `security_enforcement` (tratado como activo por defecto)
- `pytest.ini` — configuración real de test runner

### Secondary (MEDIUM confidence)
Ninguna — no hizo falta WebSearch para esta fase: todo lo relevante es interno al repositorio.

### Tertiary (LOW confidence)
- Comportamiento exacto de `model_copy(update=...)` en la versión de pydantic instalada respecto a re-ejecutar `model_validator(mode="after")` — no verificado en esta sesión, documentado como Assumption A1

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — cero dependencias nuevas, todo verificado por lectura directa del código
- Architecture: HIGH — los tres patrones (esquema servidor-driven, resolución de origin, validación por lote) están derivados de código real ya en producción, salvo el detalle de pydantic (A1)
- Pitfalls: HIGH — los 6 pitfalls están anclados a hechos verificados (ausencia de `delete()`, ausencia de código de Fase 31, línea de `components.css` medida, fuga de `webhook_url` leída literalmente), no a especulación

**Research date:** 2026-08-23
**Valid until:** 30 días — dominio estable (sin librerías externas de vida corta), pero el hallazgo de la Fase 31 sin ejecutar puede quedar obsoleto en cuanto esa fase se ejecute; si pasan más de unos días entre esta investigación y la planificación real de la Fase 32, re-verificar `ls frontend/js/nav.js` antes de planificar.
