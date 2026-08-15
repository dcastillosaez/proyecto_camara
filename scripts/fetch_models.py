"""Descarga y prepara los modelos ONNX que el repo no autodescarga (SPEC_v2.md §4.3).

Hoy solo OSNet (ReID, Fase 25): insightface autodescarga los suyos, este no.
Idempotente: si el destino ya existe y tiene el eje de batch dinamico, no
descarga nada y sale 0. Verifica sha256 y tamano exacto antes de escribir:
un ONNX es un grafo ejecutable, descargarlo de un tercero sin comprobar el
hash es una cadena de suministro sin control (ASVS V6).

Usage:
    .venv/Scripts/python.exe scripts/fetch_models.py [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ModelSpec:
    name: str
    url: str
    mirror: str
    sha256: str
    size: int
    dest: Path


OSNET = ModelSpec(
    name="osnet_x0_25_msmt17",
    url="https://huggingface.co/kornia/osnet/resolve/main/osnet_x0_25_msmt17.onnx",
    mirror=(
        "https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/"
        "osnet_x0_25_msmt17.onnx"
    ),
    # sha256 identico en las dos fuentes (verificado en el research de la Fase 25).
    sha256="e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277",
    size=907_169,
    dest=_PROJECT_ROOT / "models" / "reid" / "osnet_x0_25_msmt17_dyn.onnx",
)

MODELS = [OSNET]


def _download(url: str, dst: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp, open(dst, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_dynamic_batch(src: Path, dst: Path) -> None:
    """El export publico fija dim0=16 en entrada y salida. ORT rechaza batch 1
    y una llamada rellena a 16 cuesta 84,5 ms en vez de 4,97 ms (medido en el
    research de la Fase 25). Reescribir el eje da un grafo bit-identico
    (verificado: max|delta| = 0.0) con batch dinamico."""
    import onnx

    m = onnx.load(str(src))
    for t in list(m.graph.input) + list(m.graph.output):
        d = t.type.tensor_type.shape.dim[0]
        d.ClearField("dim_value")
        d.dim_param = "batch"
    dst.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(m, str(dst))


def _batch_dim_is_dynamic(path: Path) -> bool:
    import onnx

    m = onnx.load(str(path))
    return m.graph.input[0].type.tensor_type.shape.dim[0].dim_param != ""


def fetch(spec: ModelSpec, force: bool = False) -> int:
    if spec.dest.exists() and not force and _batch_dim_is_dynamic(spec.dest):
        print(f"[skip] {spec.name}: ya presente en {spec.dest} con batch dinamico")
        return 0

    tmp = Path(tempfile.mkdtemp()) / "model.onnx"
    try:
        _download(spec.url, tmp)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de red intenta el espejo
        print(f"[warn] {spec.name}: fallo al descargar de {spec.url}: {exc}")
        try:
            _download(spec.mirror, tmp)
        except Exception as exc2:  # noqa: BLE001
            print(f"[error] {spec.name}: fallo tambien el espejo {spec.mirror}: {exc2}")
            return 1

    actual_size = tmp.stat().st_size
    if actual_size != spec.size:
        print(
            f"[error] {spec.name}: tamano inesperado — esperado {spec.size} bytes, "
            f"obtenido {actual_size} bytes"
        )
        return 1

    actual_sha256 = _sha256(tmp)
    if actual_sha256 != spec.sha256:
        print(
            f"[error] {spec.name}: sha256 inesperado — esperado {spec.sha256}, "
            f"obtenido {actual_sha256}"
        )
        return 1

    _to_dynamic_batch(tmp, spec.dest)

    print(
        f"[ok] {spec.name}\n"
        f"  destino:  {spec.dest}\n"
        f"  bytes:    {actual_size}\n"
        f"  sha256:   OK\n"
        f"  batch:    16 -> dinamico"
    )
    return 0


def main(force: bool) -> int:
    codes = [fetch(spec, force=force) for spec in MODELS]
    return max(codes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="vuelve a descargar aunque el destino ya exista"
    )
    args = parser.parse_args()
    sys.exit(main(args.force))
