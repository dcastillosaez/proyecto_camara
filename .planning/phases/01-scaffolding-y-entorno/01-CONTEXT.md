# Phase 1: Scaffolding y entorno - Context

**Gathered:** 2026-04-16
**Status:** Ready for planning
**Source:** Generated from project artifacts (CLAUDE.md, ROADMAP.md, STATE.md)

<domain>
## Phase Boundary

Esta fase crea la base del proyecto: estructura de directorios, entorno virtual de Python 3.12, todas las dependencias instaladas y verificables, y la configuracion base documentada. No hay logica de negocio — solo infraestructura para que las fases 2-8 puedan construir encima sin friccion.

</domain>

<decisions>
## Implementation Decisions

### Estructura de directorios
- Crear `backend/` con `__init__.py` en cada modulo: `main.py`, `stream.py`, `detector.py`, `tracker.py`, `database.py`, `config.py`
- Crear `frontend/` con `index.html` y `app.js` (placeholders minimos)
- Crear `tests/` con `__init__.py`, `test_detector.py`, `test_tracker.py` (placeholders)
- Crear `data/` con `.gitkeep` (la BD se genera en runtime)

### Dependencias y versiones
- Python 3.12.x (no 3.13 — evitar features experimentales free-threaded)
- `requirements.txt` con versiones pinneadas:
  - `fastapi>=0.115`
  - `uvicorn[standard]>=0.30`
  - `opencv-python>=4.10`
  - `ultralytics>=8.4` (incluye YOLO26n)
  - `supervision>=0.25`
  - `aiosqlite>=0.20`
  - `sqlalchemy[asyncio]>=2.0`
  - `pydantic-settings>=2.0`
  - `websockets>=12.0`
- No instalar `databases` (encode) — usar SQLAlchemy 2.0 async directamente
- No instalar `python-dotenv` — pydantic-settings lo reemplaza

### Configuracion
- `.env.example` con todas las variables documentadas:
  - `CAMERA_URL=rtsp://192.168.1.132:554/stream1`
  - `YOLO_CONFIDENCE=0.45`
  - `DB_PATH=data/events.db`
  - `HOST=0.0.0.0`
  - `PORT=8000`
- `backend/config.py` con clase Settings usando pydantic-settings (placeholder funcional)

### Entorno virtual
- Usar `venv` estandar de Python, no conda ni poetry
- Directorio `.venv/` en la raiz del proyecto, anadido a `.gitignore`

### Claude's Discretion
- Formato exacto del `requirements.txt` (rangos vs pins exactos)
- Contenido placeholder de los modulos Python (imports minimos vs esqueleto con docstrings)
- Si anadir un `pyproject.toml` ademas de `requirements.txt`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Arquitectura del proyecto
- `CLAUDE.md` — Stack completo, arquitectura, flujo de datos, decisiones de diseno, variables de entorno

### Planificacion
- `.planning/ROADMAP.md` — Fases 1-8 con goals y success criteria
- `.planning/REQUIREMENTS.md` — Requisitos v1 con IDs (CAP, DET, CNT, DB, API, UI, CFG)
- `.planning/STATE.md` — Decisiones acumuladas y contexto del proyecto

</canonical_refs>

<specifics>
## Specific Ideas

- Usar `stream2` (720p) en vez de `stream1` para deteccion segun la investigacion de stack — pero eso es decision de Phase 2, aqui solo documentar ambos en `.env.example`
- El `backend/config.py` debe usar `@lru_cache` para singleton de Settings (patron recomendado por FastAPI)
- Incluir `pytest` y `httpx` en requirements para testing (httpx necesario para TestClient de FastAPI)

</specifics>

<deferred>
## Deferred Ideas

- `pyproject.toml` con metadata del proyecto — evaluar en Phase 8 (configuracion centralizada)
- Docker / docker-compose — fuera de scope de v1
- Pre-commit hooks, linting, formatting — no es prioridad para v1

</deferred>

---

*Phase: 01-scaffolding-y-entorno*
*Context gathered: 2026-04-16 via project artifact synthesis*
