"""Tests for backend.pipeline.rate.AdaptiveRate — control adaptativo de FPS."""

from __future__ import annotations

from backend.pipeline.rate import AdaptiveRate


# ─── La primera llamada siempre procesa ──────────────────────────────────────
def test_first_call_always_processes():
    r = AdaptiveRate(target_fps=8.0)
    assert r.should_process(0.0) is True


# ─── should_process respeta el target_fps con reloj simulado ────────────────
def test_should_process_respects_target_fps():
    r = AdaptiveRate(target_fps=10.0, min_fps=10.0, max_fps=10.0)
    now = 0.0
    accepted = 0
    r.should_process(now)  # primera llamada, consume t=0
    for _ in range(100):
        now += 0.01
        if r.should_process(now):
            accepted += 1
    # 1 segundo simulado a 10 fps -> ~10 aceptados, no 100
    assert 8 <= accepted <= 11


# ─── Baja de escalon bajo carga sostenida ────────────────────────────────────
def test_steps_down_under_load():
    r = AdaptiveRate(target_fps=8.0)
    for _ in range(20):
        r.observe(0.30)
    assert r.effective_fps < 8.0


# ─── No baja de min_fps ──────────────────────────────────────────────────────
def test_does_not_go_below_min_fps():
    r = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    for _ in range(100):
        r.observe(2.0)
    assert r.effective_fps == r._min_fps


# ─── Sube de escalon cuando hay margen ────────────────────────────────────────
def test_steps_up_when_headroom():
    r = AdaptiveRate(target_fps=3.0, min_fps=3.0, max_fps=12.0)
    # forzar primero un escalon bajo
    for _ in range(20):
        r.observe(0.30)
    low = r.effective_fps
    for _ in range(60):
        r.observe(0.01)
    assert r.effective_fps > low


# ─── No supera max_fps ───────────────────────────────────────────────────────
def test_does_not_exceed_max_fps():
    r = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    for _ in range(100):
        r.observe(0.001)
    assert r.effective_fps == r._max_fps


# ─── Histeresis: no oscila entre escalones ───────────────────────────────────
def test_hysteresis_avoids_oscillation():
    r = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    changes = 0
    last = r.effective_fps
    for i in range(20):
        r.observe(0.30 if i % 2 == 0 else 0.01)
        if r.effective_fps != last:
            changes += 1
            last = r.effective_fps
    assert changes <= 2


# ─── stats expone las claves documentadas ────────────────────────────────────
def test_stats_exposes_effective_fps_and_latency():
    r = AdaptiveRate(target_fps=8.0)
    r.observe(0.05)
    s = r.stats
    for key in ("effective_fps", "avg_latency", "steps_down", "steps_up"):
        assert key in s
        assert isinstance(s[key], (int, float))


# ─── Fase 36 (SCALE-08): techo externo compartido entre camaras ──────────────
def test_external_cap_clamps_effective_fps():
    r = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    r.set_external_cap(4.0)
    assert r.effective_fps == 4.0


def test_external_cap_never_raises_effective_fps_above_its_own_step():
    """El techo solo puede BAJAR el ritmo, nunca subirlo por encima de lo que
    la propia histeresis ya eligio."""
    r = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    r.set_external_cap(100.0)
    assert r.effective_fps == 8.0


def test_external_cap_none_releases_it_without_touching_internal_step():
    r = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    r.set_external_cap(4.0)
    r.set_external_cap(None)
    assert r.effective_fps == 8.0


def test_should_process_respects_external_cap():
    r = AdaptiveRate(target_fps=10.0, min_fps=10.0, max_fps=10.0)
    r.set_external_cap(2.0)
    now = 0.0
    accepted = 0
    r.should_process(now)
    for _ in range(100):
        now += 0.01
        if r.should_process(now):
            accepted += 1
    # 1 segundo simulado a 2 fps (techo), no a los 10 fps originales
    assert 1 <= accepted <= 3


def test_min_fps_is_readable():
    r = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    assert r.min_fps == 3.0


# ─── DET-08: tolerancia frente al periodo de la fuente y FPS medido ─────────
def _run(rate: AdaptiveRate, source_fps: float, seconds: float) -> int:
    accepted = 0
    period = 1.0 / source_fps
    for i in range(int(source_fps * seconds)):
        if rate.should_process(i * period):
            accepted += 1
    return accepted


def TEST_15fps_source_and_12fps_target_does_not_halve():
    """Antes: con fuente a 15 FPS y 12 pedidos solo pasaba uno de cada dos (7,5 FPS)."""
    r = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    accepted = _run(r, source_fps=15.0, seconds=10.0)
    assert 11.0 <= accepted / 10.0 <= 12.5


def TEST_never_exceeds_target_with_a_fast_source():
    r = AdaptiveRate(target_fps=8.0, min_fps=8.0, max_fps=8.0)
    accepted = _run(r, source_fps=30.0, seconds=10.0)
    assert 7.5 <= accepted / 10.0 <= 8.3


def TEST_no_burst_after_a_pause():
    r = AdaptiveRate(target_fps=10.0, min_fps=10.0, max_fps=10.0)
    assert r.should_process(0.0)
    assert r.should_process(5.0)        # tras 5 s sin frames, uno...
    assert not r.should_process(5.01)   # ...y no una rafaga para "recuperar"


def TEST_measured_fps_reflects_what_is_processed():
    r = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    assert r.measured_fps == 0.0
    _run(r, source_fps=6.0, seconds=5.0)   # la fuente no da para 12
    assert 5.5 <= r.measured_fps <= 6.5
    assert r.stats["measured_fps"] == r.measured_fps
