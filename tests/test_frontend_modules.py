"""Contrato mecanico del refactor a modulos ES (Fase 28, OPS-01/OPS-02/OPS-03).

No hay framework de test JS en el repo (sin package.json). Este fichero cubre solo las
propiedades mecanicas verificables desde Python: ficheros locked por 28-CONTEXT.md, limite de
300 lineas, ausencia de logica inline en index.html, y el tipo MIME real servido por la app
ASGI. La paridad funcional completa (video, PTZ, zonas, grabaciones, etc.) es un checklist
manual firmado en el SUMMARY de la puerta de fase (28-09-PLAN.md), igual que 27-10.

La mayoria de estos tests estan en rojo hasta que 28-08-PLAN.md termina la fase: es el estado
esperado mientras 28-02..28-07 van creando los modulos uno a uno.
"""
import re
from pathlib import Path

from starlette.testclient import TestClient

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
LINE_LIMIT = 300

LOCKED_CSS = ["base.css", "layout.css", "components.css"]

LOCKED_JS = [
    "app.js",
    "api.js",
    "websocket.js",
    "views/dashboard.js",
    "views/dashboard-ptz.js",
    "views/dashboard-events.js",
    "views/dashboard-observability.js",
    "components/videoCanvas.js",
    "components/zoneEditor.js",
    "components/eventCard.js",
    "components/detectionClasses.js",
    "components/personGallery.js",
]


def TEST_css_modules_exist():
    missing = [n for n in LOCKED_CSS if not (FRONTEND / "css" / n).is_file()]
    assert not missing, f"faltan CSS locked por 28-CONTEXT.md: {missing}"


def TEST_js_modules_exist():
    missing = [rel for rel in LOCKED_JS if not (FRONTEND / "js" / rel).is_file()]
    assert not missing, f"faltan modulos JS locked por 28-CONTEXT.md: {missing}"


def TEST_line_limit():
    offenders = []
    paths = list((FRONTEND / "js").rglob("*.js")) + list((FRONTEND / "css").glob("*.css"))
    for path in paths:
        n = len(path.read_text(encoding="utf-8").splitlines())
        if n > LINE_LIMIT:
            offenders.append(f"{path.relative_to(FRONTEND)}: {n} lineas")
    assert not offenders, f"modulos por encima de {LINE_LIMIT} lineas: {offenders}"


def TEST_no_inline_logic():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert re.search(r"<style[\s>]", html) is None, "sigue habiendo un <style> inline en index.html"
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag, f"<script> inline sin src encontrado en index.html: {tag}"


def TEST_app_entry_point_is_real():
    app_js = FRONTEND / "js" / "app.js"
    content = app_js.read_text(encoding="utf-8")
    assert len(content.splitlines()) > 10, "frontend/js/app.js sigue pareciendo el stub de 2 lineas"
    assert "DOMContentLoaded" in content, "app.js debe orquestar el arranque en DOMContentLoaded"
    stub = FRONTEND / "app.js"
    assert not stub.exists(), "frontend/app.js (stub v1.2) debe eliminarse, no quedar huerfano junto al real"


def TEST_static_js_mime_type():
    from backend.main import app
    client = TestClient(app)
    res = client.get("/static/js/app.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]


def TEST_static_css_served():
    from backend.main import app
    client = TestClient(app)
    res = client.get("/static/css/base.css")
    assert res.status_code == 200
    assert "css" in res.headers["content-type"]


def TEST_root_serves_index_html():
    from backend.main import app
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
