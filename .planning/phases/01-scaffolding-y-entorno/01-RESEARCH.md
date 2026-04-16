# Phase 1: Scaffolding y entorno - Research

**Researched:** 2026-04-16
**Domain:** Project scaffolding, Python virtual environment, dependency management
**Confidence:** HIGH

## Summary

Esta fase es puramente de infraestructura: crear la estructura de directorios, el entorno virtual con Python 3.12, instalar dependencias, y documentar la configuracion. No hay logica de negocio. El riesgo principal es que el sistema tiene Python 3.14 como default, pero Python 3.12.10 esta disponible via `py -3.12`. El entorno virtual debe crearse explicitamente con `py -3.12 -m venv .venv` para evitar que tome el Python equivocado.

El proyecto actualmente solo contiene `CLAUDE.md` y `.planning/` -- no hay .gitignore, ni directorios de codigo, ni requirements.txt. Todo se crea desde cero.

**Recomendacion principal:** Crear el venv con `py -3.12 -m venv .venv`, activarlo, instalar dependencias con pip, y verificar imports. Anadir .gitignore antes de cualquier otra cosa para evitar commits accidentales de .venv/.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Estructura de directorios: `backend/` (con `__init__.py`, main.py, stream.py, detector.py, tracker.py, database.py, config.py), `frontend/` (index.html, app.js), `tests/` (con __init__.py, test_detector.py, test_tracker.py), `data/` (con .gitkeep)
- Dependencias en `requirements.txt` con versiones minimas pinneadas (fastapi>=0.115, uvicorn[standard]>=0.30, opencv-python>=4.10, ultralytics>=8.4, supervision>=0.25, aiosqlite>=0.20, sqlalchemy[asyncio]>=2.0, pydantic-settings>=2.0, websockets>=12.0)
- No instalar `databases` (encode) ni `python-dotenv`
- `.env.example` con CAMERA_URL, YOLO_CONFIDENCE, DB_PATH, HOST, PORT
- `backend/config.py` con clase Settings usando pydantic-settings (placeholder funcional)
- Entorno virtual con `venv` estandar, directorio `.venv/`, en `.gitignore`

### Claude's Discretion
- Formato exacto del `requirements.txt` (rangos vs pins exactos)
- Contenido placeholder de los modulos Python (imports minimos vs esqueleto con docstrings)
- Si anadir un `pyproject.toml` ademas de `requirements.txt`

### Deferred Ideas (OUT OF SCOPE)
- `pyproject.toml` con metadata del proyecto (evaluar en Phase 8)
- Docker / docker-compose
- Pre-commit hooks, linting, formatting

</user_constraints>

## Standard Stack

### Core (a instalar en esta fase)
| Paquete | Version minima | Proposito | Verificado |
|---------|---------------|-----------|------------|
| Python | 3.12.10 | Runtime | `py -3.12 --version` confirma 3.12.10 en el sistema |
| fastapi | >=0.115 | Framework web | Decision bloqueada |
| uvicorn[standard] | >=0.30 | Servidor ASGI | Decision bloqueada |
| opencv-python | >=4.10 | Captura RTSP + procesamiento | Decision bloqueada |
| ultralytics | >=8.4 | YOLO26n para deteccion | Decision bloqueada |
| supervision | >=0.25 | ByteTrack + LineZone | Decision bloqueada |
| aiosqlite | >=0.20 | Driver async SQLite | Decision bloqueada |
| sqlalchemy[asyncio] | >=2.0 | ORM async | Decision bloqueada |
| pydantic-settings | >=2.0 | Configuracion con validacion | Decision bloqueada |
| websockets | >=12.0 | Transporte WebSocket | Decision bloqueada |

### Testing (anadir al requirements.txt)
| Paquete | Proposito | Nota |
|---------|-----------|------|
| pytest | Test runner | Mencionado en CONTEXT.md specifics |
| httpx | TestClient de FastAPI | Mencionado en CONTEXT.md specifics |

### Instalacion
```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate   # Windows con bash/MSYS2
pip install --upgrade pip
pip install -r requirements.txt
```

**Nota Windows:** En bash de Git/MSYS2 el activate esta en `.venv/Scripts/activate`, no en `.venv/bin/activate` como en Linux/Mac.

## Architecture Patterns

### Estructura de directorios (decision bloqueada)
```
Proyecto_Camara/
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── stream.py
│   ├── detector.py
│   ├── tracker.py
│   ├── database.py
│   └── config.py
├── frontend/
│   ├── index.html
│   └── app.js
├── tests/
│   ├── __init__.py
│   ├── test_detector.py
│   └── test_tracker.py
├── data/
│   └── .gitkeep
├── .env.example
├── .gitignore
├── requirements.txt
└── CLAUDE.md
```

### Pattern: config.py con pydantic-settings
```python
# backend/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    camera_url: str = "rtsp://192.168.1.132:554/stream1"
    yolo_confidence: float = 0.45
    db_path: str = "data/events.db"
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env"}

@lru_cache
def get_settings() -> Settings:
    return Settings()
```
Fuente: patron recomendado por FastAPI docs (https://fastapi.tiangolo.com/advanced/settings/)

### Pattern: Placeholder minimo para modulos
Cada modulo de `backend/` debe tener al menos un docstring y los imports que se usaran en fases futuras, pero sin logica funcional. Esto permite que `python -c "import backend.main"` funcione como smoke test.

### Anti-Patterns a evitar
- **No crear el venv con el Python default del sistema (3.14):** Ultralytics y opencv-python pueden no ser compatibles con 3.14. Usar explicitamente `py -3.12`.
- **No hacer `pip install` fuera del venv:** Verificar siempre que el prompt muestra `(.venv)` o que `which python` apunta a `.venv/`.

## Don't Hand-Roll

| Problema | No construir | Usar en su lugar | Por que |
|----------|-------------|-----------------|---------|
| Lectura de .env | Parser manual de .env | pydantic-settings | Validacion de tipos, valores por defecto, fail-fast al arrancar |
| Gitignore para Python | Escribir uno a mano | Template github/gitignore Python | Cubre casos edge (bytecode, eggs, IDEs, etc.) |

## Common Pitfalls

### Pitfall 1: Python version mismatch
**Que pasa:** Se crea el venv con Python 3.14 (default del sistema) en lugar de 3.12.
**Por que:** `python` y `python3` resuelven a 3.14 en este sistema. Solo `py -3.12` da la version correcta.
**Como evitar:** Siempre usar `py -3.12 -m venv .venv`. Verificar despues con `.venv/Scripts/python --version`.
**Senales de alerta:** Errores de compatibilidad al instalar ultralytics u opencv-python.

### Pitfall 2: Activate path en Windows bash
**Que pasa:** Se usa `source .venv/bin/activate` que no existe en Windows.
**Por que:** En Windows, venv pone el script en `Scripts/`, no en `bin/`.
**Como evitar:** Usar `source .venv/Scripts/activate` en bash/MSYS2.

### Pitfall 3: opencv-python build desde source
**Que pasa:** La instalacion de opencv-python tarda 30+ minutos compilando desde source.
**Por que:** Si no hay wheel precompilado para la combinacion Python version + OS + arquitectura.
**Como evitar:** Usar Python 3.12 donde hay wheels precompilados confirmados. No usar 3.14.

### Pitfall 4: Ultralytics descarga modelos al primer uso
**Que pasa:** `import ultralytics` funciona, pero `YOLO("yolo26n.pt")` descarga ~6 MB del modelo la primera vez.
**Por que:** Los pesos no vienen con el paquete pip.
**Como evitar:** Esto es esperado. No es un problema de scaffolding, pero documentarlo para Phase 3.

### Pitfall 5: .gitignore ausente permite commit de .venv/
**Que pasa:** Se hace git add y se incluyen los 200+ MB de .venv/.
**Por que:** No hay .gitignore en el proyecto actualmente.
**Como evitar:** Crear .gitignore como primera accion, antes de crear el venv.

## Environment Availability

| Dependencia | Requerida por | Disponible | Version | Fallback |
|-------------|--------------|------------|---------|----------|
| Python 3.12 | Todo el proyecto | Si | 3.12.10 | -- |
| pip (en 3.12) | Instalacion de paquetes | Si | 25.0.1 | -- |
| venv module | Entorno virtual | Si | Built-in | -- |
| git | Control de versiones | Si | (repo ya existe) | -- |
| py launcher | Seleccionar version Python | Si | Disponible en PATH | Ruta completa a python3.12.exe |

**Ruta completa de Python 3.12:** `C:\Users\DAVID GAMING PC\AppData\Local\Programs\Python\Python312\python.exe`

**Dependencias que faltan:** Ninguna. Todo lo necesario esta instalado.

## Validation Architecture

### Test Framework
| Propiedad | Valor |
|-----------|-------|
| Framework | pytest (a instalar en esta fase) |
| Config file | Ninguno (crear pytest.ini o seccion en pyproject.toml si se decide) |
| Quick run command | `pytest tests/ -v` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements -> Test Map

Esta fase no tiene requirement IDs formales (es infraestructura de soporte). Los criterios de exito se verifican con comandos directos:

| Criterio | Verificacion | Tipo | Comando |
|----------|-------------|------|---------|
| Venv funcional con dependencias | Smoke test de imports | smoke | `py -3.12 -c "import fastapi, cv2, ultralytics, supervision"` (dentro del venv) |
| Estructura de directorios existe | Verificar paths | smoke | `ls backend/main.py frontend/index.html tests/test_detector.py data/.gitkeep` |
| .env.example tiene todas las variables | Verificar contenido | smoke | `grep -c '=' .env.example` (debe dar 5) |
| config.py funcional | Import test | smoke | `python -c "from backend.config import get_settings; s = get_settings(); print(s.camera_url)"` |

### Wave 0 Gaps
- [ ] `pytest` y `httpx` en requirements.txt -- necesarios para testing en fases posteriores
- [ ] Archivos test placeholder en `tests/` -- ya contemplados en la estructura

## Discretion Recommendations

### Formato de requirements.txt
**Recomendacion:** Usar version minima con operador `>=` (como ya esta en CONTEXT.md), no pins exactos con `==`. Razon: esto es un proyecto local sin CI/CD ni deploys a produccion; la flexibilidad de `>=` evita tener que actualizar el fichero constantemente. Si en Phase 8 se quiere reproducibilidad, se puede generar un `requirements.lock` con `pip freeze`.

### Contenido placeholder de modulos
**Recomendacion:** Imports minimos + docstring de una linea. No esqueletos con funciones vacias -- eso se hace en la fase correspondiente. Cada fichero debe ser importable sin error pero sin logica ficticia que luego haya que borrar.

Ejemplo:
```python
"""Stream capture module -- RTSP frame acquisition."""
```

### pyproject.toml
**Recomendacion:** No crear en esta fase. Esta diferido a Phase 8 segun CONTEXT.md. El requirements.txt es suficiente para el flujo actual.

## Sources

### Primary (HIGH confidence)
- Verificacion directa del sistema: `py -3.12 --version` -> 3.12.10
- Verificacion directa: `py --list` muestra 3.14 y 3.12 disponibles
- Verificacion directa: `py -3.12 -m venv --help` funciona
- Verificacion directa: pip 25.0.1 disponible en Python 3.12
- FastAPI settings docs: https://fastapi.tiangolo.com/advanced/settings/

### Secondary (MEDIUM confidence)
- Compatibilidad de opencv-python con Python 3.12: wheels precompilados disponibles en PyPI (verificado por experiencia general, no probado en este sistema)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- todas las versiones y dependencias definidas en CONTEXT.md, Python 3.12 verificado en el sistema
- Architecture: HIGH -- estructura de directorios bloqueada en CONTEXT.md, patron de config.py documentado en FastAPI docs
- Pitfalls: HIGH -- verificados directamente en el entorno (Python default es 3.14, no 3.12; paths de activate en Windows)

**Research date:** 2026-04-16
**Valid until:** 2026-05-16 (fase estable, sin dependencias de APIs cambiantes)
