"""Tests del selector de dispositivo de inferencia (Fase 38, 38-01). Pasan sin GPU."""

import sys

import pytest

from backend.inference import device as device_module
from backend.inference.device import DeviceChoice, resolve_device


@pytest.fixture(autouse=True)
def _clear_cache():
    resolve_device.cache_clear()
    yield
    resolve_device.cache_clear()


def _probes(monkeypatch, torch_ok: bool, ort_ok: bool) -> None:
    monkeypatch.setattr(device_module, "_torch_cuda_available", lambda: torch_ok)
    monkeypatch.setattr(device_module, "_ort_cuda_available", lambda: ort_ok)


def TEST_cpu_mode_never_probes(monkeypatch):
    def _boom():
        raise AssertionError("la ruta cpu no debe sondear")

    monkeypatch.setattr(device_module, "_torch_cuda_available", _boom)
    monkeypatch.setattr(device_module, "_ort_cuda_available", _boom)
    choice = resolve_device("cpu")
    assert choice.torch_device is None
    assert choice.onnx_providers == ("CPUExecutionProvider",)
    assert choice.mode == "cpu"
    assert "forzado" in choice.reason


def TEST_auto_falls_back_to_cpu_without_cuda(monkeypatch):
    _probes(monkeypatch, False, False)
    choice = resolve_device("auto")
    assert choice.torch_device is None
    assert choice.onnx_providers == ("CPUExecutionProvider",)
    assert choice.mode == "auto"


def TEST_auto_prefers_cuda_when_both_probes_true(monkeypatch):
    _probes(monkeypatch, True, True)
    choice = resolve_device("auto")
    assert choice.torch_device == "cuda:0"
    assert choice.onnx_providers == ("CUDAExecutionProvider", "CPUExecutionProvider")


def TEST_mixed_availability_torch_only(monkeypatch):
    _probes(monkeypatch, True, False)
    choice = resolve_device("auto")
    assert choice.torch_device == "cuda:0"
    assert choice.onnx_providers == ("CPUExecutionProvider",)


def TEST_mixed_availability_onnx_only(monkeypatch):
    _probes(monkeypatch, False, True)
    choice = resolve_device("auto")
    assert choice.torch_device is None
    assert choice.onnx_providers == ("CUDAExecutionProvider", "CPUExecutionProvider")


def TEST_cuda_forced_raises_without_any_cuda(monkeypatch):
    _probes(monkeypatch, False, False)
    with pytest.raises(RuntimeError, match="inference_device='cuda'"):
        resolve_device("cuda")


@pytest.mark.parametrize("torch_ok,ort_ok", [(True, False), (False, True), (True, True)])
def TEST_cuda_forced_uses_cuda_only_where_possible(monkeypatch, torch_ok, ort_ok):
    _probes(monkeypatch, torch_ok, ort_ok)
    choice = resolve_device("cuda")
    assert (choice.torch_device == "cuda:0") is torch_ok
    assert (choice.onnx_providers[0] == "CUDAExecutionProvider") is ort_ok
    assert choice.onnx_providers[-1] == "CPUExecutionProvider"


def TEST_probes_return_false_without_packages(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    assert device_module._torch_cuda_available() is False
    assert device_module._ort_cuda_available() is False


def TEST_resolve_device_is_cached_per_mode(monkeypatch):
    _probes(monkeypatch, False, False)
    first = resolve_device("auto")
    assert resolve_device("auto") is first
    assert isinstance(first, DeviceChoice)
    assert resolve_device("cpu") is not first
