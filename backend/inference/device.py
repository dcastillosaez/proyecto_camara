"""Punto UNICO de decision del dispositivo de inferencia (Fase 38, SCALE-11/SCALE-12).

Mismo rol que `create_event_bus` (events/bus.py) para el bus de la Fase 37: la
configuracion se traduce aqui una sola vez y el resto del codigo no vuelve a ramificar.

Tres reglas no negociables, todas verificadas en 38-RESEARCH.md:
1. La ruta CPU devuelve `torch_device=None` — a Ultralytics NO se le pasa device en
   absoluto, porque `select_device("cpu")` escribe CUDA_VISIBLE_DEVICES="" a nivel de
   PROCESO (ultralytics/utils/torch_utils.py) y cegaria tambien al CUDA EP de
   onnxruntime construido despues.
2. La disponibilidad es POR FAMILIA de motor: torch puede tener CUDA y el build de
   onnxruntime no (o al reves). Un unico booleano `gpu_available` enmascararia ese caso.
3. Los imports de torch/onnxruntime son DIFERIDOS y envueltos en try/except: el modulo
   debe ser importable y testeable sin ninguno de los dos.

Extensibilidad (DirectML u otro proveedor): anadir una entrada a ONNX_PROVIDERS y su
sonda correspondiente. No hay que reescribir la logica.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

# Orden = politica de fallback de onnxruntime: preferido primero, CPUExecutionProvider
# SIEMPRE al final. ORT no lanza cuando falta un provider (verificado en 1.28.0): lo
# descarta y sigue, asi que la lista ordenada ES el mecanismo de fallback.
ONNX_PROVIDERS: dict[str, tuple[str, ...]] = {
    "cuda": ("CUDAExecutionProvider", "CPUExecutionProvider"),
    "cpu": ("CPUExecutionProvider",),
}

_CPU_ONLY = ONNX_PROVIDERS["cpu"]


@dataclass(frozen=True)
class DeviceChoice:
    """Intencion resuelta. Cada motor la traduce a su propio dialecto."""

    torch_device: str | None
    onnx_providers: tuple[str, ...]
    mode: str
    reason: str


def _torch_cuda_available() -> bool:
    """True si ESTE proceso puede usar CUDA con torch. Nunca lanza."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _ort_cuda_available() -> bool:
    """True si ESTE build de onnxruntime expone el CUDA EP. Nunca lanza.

    get_available_providers() lista lo que el build puede usar; la lista de todos los
    providers que ORT conoce en abstracto incluiria CUDAExecutionProvider incluso en un
    build CPU — usarla seria el bug clasico.
    """
    try:
        import onnxruntime as ort

        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def _ort_providers_repr() -> str:
    try:
        import onnxruntime as ort

        return str(ort.get_available_providers())
    except Exception:
        return "<onnxruntime no importable>"


@lru_cache(maxsize=None)
def resolve_device(mode: str) -> DeviceChoice:
    """Traduce `Settings.inference_device` al dispositivo efectivo por familia.

    Cacheado por proceso para que los tres motores vean la MISMA decision aunque algo
    mute el entorno entre construcciones. Los tests deben llamar a
    `resolve_device.cache_clear()` entre casos.
    """
    if mode == "cpu":
        choice = DeviceChoice(
            torch_device=None,
            onnx_providers=_CPU_ONLY,
            mode=mode,
            reason="CPU forzado por configuracion (inference_device=cpu)",
        )
        logger.info("Dispositivo de inferencia: %s", choice.reason)
        return choice

    torch_ok = _torch_cuda_available()
    ort_ok = _ort_cuda_available()

    if mode == "cuda" and not torch_ok and not ort_ok:
        raise RuntimeError(
            "inference_device='cuda' pero ninguna familia de motores puede usar CUDA: "
            f"torch.cuda.is_available()={torch_ok}, "
            f"onnxruntime.get_available_providers()={_ort_providers_repr()}. "
            "Usa inference_device='auto' para caer a CPU automaticamente."
        )

    choice = DeviceChoice(
        torch_device="cuda:0" if torch_ok else None,
        onnx_providers=ONNX_PROVIDERS["cuda"] if ort_ok else _CPU_ONLY,
        mode=mode,
        reason=f"inference_device={mode}: torch_cuda={torch_ok}, onnx_cuda={ort_ok}",
    )
    logger.info(
        "Dispositivo de inferencia: torch=%s onnx=%s (%s)",
        choice.torch_device or "cpu",
        choice.onnx_providers[0],
        choice.reason,
    )
    return choice
