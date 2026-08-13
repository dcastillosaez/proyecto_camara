"""Tests de arquitectura — invariantes de concurrencia del pipeline (PIPE-06).

Baratos, rapidos y protegen mejor que cualquier revision manual: se
ejecutan en cada push y senalan fichero, linea y funcion infractora.
"""

from __future__ import annotations

import ast
from pathlib import Path

PIPELINE_DIR = Path("backend/pipeline")
BACKEND_DIR = Path("backend")

INFERENCE_CALLS = {
    "detect_sv", "detect", "embed", "process_crop", "process_crop_scored",
    "identify_or_register",
}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _functions(tree: ast.AST) -> list[ast.FunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]


def _async_functions(tree: ast.AST) -> list[ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]


def _thread_targets(tree: ast.AST) -> set[str]:
    """Nombres de metodos pasados como target= a un threading.Thread."""
    targets: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_thread = (
            (isinstance(func, ast.Attribute) and func.attr == "Thread")
            or (isinstance(func, ast.Name) and func.id == "Thread")
        )
        if not is_thread:
            continue
        for kw in node.keywords:
            if kw.arg != "target":
                continue
            if isinstance(kw.value, ast.Attribute):
                targets.add(kw.value.attr)
            elif isinstance(kw.value, ast.Name):
                targets.add(kw.value.id)
    return targets


# ─── Ningun hilo ejecuta await ───────────────────────────────────────────────
def test_no_await_in_worker_threads():
    offenders: list[str] = []
    for path in sorted(PIPELINE_DIR.rglob("*.py")):
        tree = _parse(path)
        targets = _thread_targets(tree)
        if not targets:
            continue
        for fn in _functions(tree):
            if fn.name not in targets:
                continue
            for node in ast.walk(fn):
                if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
                    offenders.append(f"{path}:{node.lineno} target de Thread '{fn.name}' usa await")
        # una corrutina jamas puede ser target de un Thread
        for fn in _async_functions(tree):
            if fn.name in targets:
                offenders.append(f"{path}:{fn.lineno} corrutina '{fn.name}' usada como target de Thread")
    assert not offenders, "Await dentro de hilos:\n" + "\n".join(offenders)


# ─── Ninguna corrutina ejecuta inferencia ────────────────────────────────────
def test_no_inference_in_coroutines():
    """
    Una corrutina puede *encargar* inferencia pasando la funcion a
    ``asyncio.to_thread(fn, ...)`` — eso la saca del event loop y es el
    patron correcto. Lo que no puede es *invocarla*: ``fn(...)`` dentro de
    una corrutina bloquea el loop entero mientras corre YOLO o dlib.

    Por eso el chequeo mira solo nodos ``ast.Call``: ``to_thread(x.detect_sv)``
    referencia el atributo sin llamarlo y no cuenta como infraccion.
    """
    offenders: list[str] = []
    for path in sorted(BACKEND_DIR.rglob("*.py")):
        tree = _parse(path)
        for fn in _async_functions(tree):
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name)
                    else None
                )
                if name in INFERENCE_CALLS:
                    offenders.append(f"{path}:{node.lineno} {fn.name} -> {name}()")
    assert not offenders, (
        "Inferencia ejecutada dentro de una corrutina (usar asyncio.to_thread):\n"
        + "\n".join(offenders)
    )


# ─── CaptureWorker sigue siendo puro (invariante de la Fase 17) ─────────────
def test_capture_worker_stays_pure():
    src = (PIPELINE_DIR / "capture.py").read_text(encoding="utf-8").lower()
    for forbidden in ("yolo", "detector", "recogn", "zone", "heatmap", "tracker"):
        assert forbidden not in src, f"CaptureWorker no debe referenciar '{forbidden}'"


# ─── Sin deserializacion insegura (SEC-15) ──────────────────────────────────
def test_no_pickle_in_backend():
    offenders: list[str] = []
    for path in sorted(BACKEND_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "pickle" in line:
                offenders.append(f"{path}:{lineno} {line.strip()}")
    assert not offenders, "pickle no debe aparecer en backend/ (SEC-15):\n" + "\n".join(offenders)


# ─── El pipeline no conoce la capa web ───────────────────────────────────────
def test_pipeline_modules_do_not_import_fastapi():
    offenders: list[str] = []
    for path in sorted(PIPELINE_DIR.rglob("*.py")):
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for n in names:
                if n.split(".")[0] in {"fastapi", "starlette"}:
                    offenders.append(f"{path}:{node.lineno} importa {n}")
    assert not offenders, "El pipeline no debe conocer la capa web:\n" + "\n".join(offenders)
