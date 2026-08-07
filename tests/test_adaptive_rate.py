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
