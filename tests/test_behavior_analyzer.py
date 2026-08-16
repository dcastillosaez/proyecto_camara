"""Tests para BehaviorAnalyzer (Fase 26, BEH-01/BEH-02/BEH-03/BEH-05).

Dominio puro: sin hilos, sin bus, sin reloj real. El reloj se inyecta como
float sintetico, igual que en test_track_gallery.py y
test_identity_state_machine.py. Las trayectorias son sinteticas y deterministas
(patron de las Fases 24/25): cada test construye la secuencia de posiciones
minima que aisla el comportamiento bajo prueba, sin supresion mutua en el
dominio (D-03).
"""

from __future__ import annotations

from backend.perception.behavior import BehaviorAnalyzer, BehaviorFinding, BehaviorKind


def _walk(x0, y0, vx, vy, secs, fps=8.0):
    """Trayectoria rectilinea: devuelve [(t, x, y), ...] a fps constante."""
    n = int(secs * fps)
    return [(i / fps, x0 + vx * i / fps, y0 + vy * i / fps) for i in range(n)]


def _jitter_run(analyzer, track_id, cx, cy, n, dt, amp, zone_membership=None, start_t=0.0):
    """Alimenta `n` frames de jitter ciclico (±amp) alrededor de (cx, cy).

    Ciclo de 3 fases (-amp, 0, +amp): el desplazamiento neto entre fases
    consecutivas es `amp`, no `2*amp` (nunca salta directamente de -amp a
    +amp). Devuelve la lista acumulada de findings.
    """
    zone_membership = zone_membership or {}
    findings: list[BehaviorFinding] = []
    for i in range(n):
        t = start_t + i * dt
        x = cx + amp * ((i % 3) - 1)
        findings.extend(analyzer.analyze({track_id: (x, cy)}, zone_membership, {}, t))
    return findings


# ─── IMMOBILE (BEH-02, criterio 1) ────────────────────────────────────────────

def TEST_immobile_after_threshold():
    analyzer = BehaviorAnalyzer()
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=561, dt=0.125, amp=2.0)
    imm = [f for f in findings if f.kind is BehaviorKind.IMMOBILE]
    assert len(imm) == 1
    assert imm[0].duration_s > 60
    assert imm[0].net_displacement_px <= 20


def TEST_immobile_resets_when_track_moves():
    analyzer = BehaviorAnalyzer()
    # Fase 1: 30 s cerca de (100, 100) — no debe emitir todavia (< 60 s).
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=240, dt=0.125, amp=2.0)
    assert not any(f.kind is BehaviorKind.IMMOBILE for f in findings)

    # Salto de 400 px: el ancla se resetea.
    last_t = 239 * 0.125
    jump_t = last_t + 0.125
    findings.extend(analyzer.analyze({1: (500.0, 500.0)}, {}, {}, jump_t))
    assert not any(f.kind is BehaviorKind.IMMOBILE for f in findings)

    # Fase 2: 70 s cerca de (500, 500) tras el salto — emite una vez.
    findings.extend(
        _jitter_run(analyzer, 1, 500.0, 500.0, n=561, dt=0.125, amp=2.0, start_t=jump_t + 0.125)
    )
    imm = [f for f in findings if f.kind is BehaviorKind.IMMOBILE]
    assert len(imm) == 1
    assert imm[0].duration_s > 60


def TEST_immobile_latch_emits_once_per_episode():
    analyzer = BehaviorAnalyzer()
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=561, dt=0.125, amp=2.0)
    findings.extend(
        _jitter_run(analyzer, 1, 100.0, 100.0, n=200, dt=0.125, amp=2.0, start_t=561 * 0.125)
    )
    imm = [f for f in findings if f.kind is BehaviorKind.IMMOBILE]
    assert len(imm) == 1


# ─── LOITERING (BEH-01, criterio 1, D-02, D-04) ───────────────────────────────

def TEST_loiter_in_zone_after_threshold():
    analyzer = BehaviorAnalyzer()
    findings = _jitter_run(
        analyzer, 1, 100.0, 100.0, n=261, dt=0.5, amp=30.0, zone_membership={"z1": {1}}
    )
    loit = [f for f in findings if f.kind is BehaviorKind.LOITERING]
    assert len(loit) == 1
    assert loit[0].zone_id == "z1"
    assert loit[0].duration_s > 120
    assert loit[0].net_displacement_px < 80


def TEST_loiter_falls_back_to_implicit_scene_without_zones():
    analyzer = BehaviorAnalyzer(loiter_require_zone=False)
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=261, dt=0.5, amp=30.0)
    loit = [f for f in findings if f.kind is BehaviorKind.LOITERING]
    assert len(loit) == 1
    assert loit[0].zone_id is None


def TEST_loiter_requires_zone_when_configured():
    analyzer = BehaviorAnalyzer(loiter_require_zone=True)
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=261, dt=0.5, amp=30.0)
    loit = [f for f in findings if f.kind is BehaviorKind.LOITERING]
    assert len(loit) == 0


def TEST_loiter_emits_once_per_overlapping_zone():
    analyzer = BehaviorAnalyzer()
    findings = _jitter_run(
        analyzer, 1, 100.0, 100.0, n=261, dt=0.5, amp=30.0,
        zone_membership={"z1": {1}, "z2": {1}},
    )
    loit = [f for f in findings if f.kind is BehaviorKind.LOITERING]
    assert len(loit) == 2
    assert {f.zone_id for f in loit} == {"z1", "z2"}


def TEST_loiter_latch_emits_once_per_episode():
    analyzer = BehaviorAnalyzer()
    findings = _jitter_run(
        analyzer, 1, 100.0, 100.0, n=261, dt=0.5, amp=30.0, zone_membership={"z1": {1}}
    )
    findings.extend(
        _jitter_run(
            analyzer, 1, 100.0, 100.0, n=200, dt=0.5, amp=30.0,
            zone_membership={"z1": {1}}, start_t=261 * 0.5,
        )
    )
    loit = [f for f in findings if f.kind is BehaviorKind.LOITERING]
    assert len(loit) == 1


# ─── RUNNING (BEH-02, criterio 1) ─────────────────────────────────────────────

def TEST_running_over_speed_threshold():
    analyzer = BehaviorAnalyzer()
    history = _walk(0.0, 0.0, 400.0, 0.0, 2.0)
    t_now, x_now, y_now = history[-1]
    findings = analyzer.analyze({1: (x_now, y_now)}, {}, {1: history}, t_now)
    run = [f for f in findings if f.kind is BehaviorKind.RUNNING]
    assert len(run) == 1
    assert run[0].speed_px_s > 350
    assert run[0].duration_s == analyzer._run_window_secs


def TEST_running_ignores_insufficient_history():
    analyzer = BehaviorAnalyzer()
    history = _walk(0.0, 0.0, 400.0, 0.0, 0.2)
    t_now, x_now, y_now = history[-1]
    findings = analyzer.analyze({1: (x_now, y_now)}, {}, {1: history}, t_now)
    assert not any(f.kind is BehaviorKind.RUNNING for f in findings)


def TEST_running_ignores_jitter():
    analyzer = BehaviorAnalyzer()
    history = [(i / 8.0, 5.0 * ((i % 3) - 1), 0.0) for i in range(17)]
    t_now, x_now, y_now = history[-1]
    findings = analyzer.analyze({1: (x_now, y_now)}, {}, {1: history}, t_now)
    assert not any(f.kind is BehaviorKind.RUNNING for f in findings)


def TEST_running_latch_rearms_below_hysteresis():
    analyzer = BehaviorAnalyzer()
    history: list[tuple[float, float, float]] = []
    findings: list[BehaviorFinding] = []
    dt = 0.125
    x = 0.0

    # Fase A: 2 s a 400 px/s (dx=50 px por paso de 0.125 s) -> 1er RUNNING.
    for i in range(17):
        t = i * dt
        x = i * 50.0
        history.append((t, x, 0.0))
        findings.extend(analyzer.analyze({1: (x, 0.0)}, {}, {1: list(history)}, t))
    run1 = [f for f in findings if f.kind is BehaviorKind.RUNNING]
    assert len(run1) == 1

    # Fase B: 2 s parado -> velocidad de ventana cae por debajo de 350*0.8, re-armado.
    t_start = history[-1][0]
    for i in range(1, 17):
        t = t_start + i * dt
        history.append((t, x, 0.0))
        findings.extend(analyzer.analyze({1: (x, 0.0)}, {}, {1: list(history)}, t))
    run2 = [f for f in findings if f.kind is BehaviorKind.RUNNING]
    assert len(run2) == 1

    # Fase C: acelera de nuevo -> 2o RUNNING.
    t_start2 = history[-1][0]
    for i in range(1, 17):
        t = t_start2 + i * dt
        x += 50.0
        history.append((t, x, 0.0))
        findings.extend(analyzer.analyze({1: (x, 0.0)}, {}, {1: list(history)}, t))
    run3 = [f for f in findings if f.kind is BehaviorKind.RUNNING]
    assert len(run3) == 2


# ─── CROWD (BEH-03, criterio 1) ───────────────────────────────────────────────

def TEST_crowd_detected_at_threshold():
    analyzer = BehaviorAnalyzer(crowd_threshold=5)
    findings = analyzer.analyze({t: (1.0, 1.0) for t in range(5)}, {}, {}, 0.0)
    crowd = [f for f in findings if f.kind is BehaviorKind.CROWD]
    assert len(crowd) == 1
    assert crowd[0].track_count == 5


def TEST_crowd_latch_emits_once_while_crowded():
    analyzer = BehaviorAnalyzer(crowd_threshold=5)
    findings: list[BehaviorFinding] = []
    for i in range(100):
        findings.extend(analyzer.analyze({t: (1.0, 1.0) for t in range(5)}, {}, {}, float(i)))
    crowd = [f for f in findings if f.kind is BehaviorKind.CROWD]
    assert len(crowd) == 1


# ─── Payload (BEH-05) ──────────────────────────────────────────────────────────

def TEST_payload_magnitudes_use_exact_keys():
    imm = BehaviorFinding(kind=BehaviorKind.IMMOBILE, track_id=1, duration_s=61.0,
                          net_displacement_px=3.2)
    assert set(imm.magnitudes().keys()) == {"duration_s", "net_displacement_px"}

    loit = BehaviorFinding(kind=BehaviorKind.LOITERING, track_id=1, zone_id="z1",
                           duration_s=130.0, net_displacement_px=10.0)
    assert set(loit.magnitudes().keys()) == {"duration_s", "net_displacement_px"}

    run = BehaviorFinding(kind=BehaviorKind.RUNNING, track_id=1, speed_px_s=400.0,
                          duration_s=1.0)
    assert set(run.magnitudes().keys()) == {"speed_px_s", "duration_s"}

    crowd = BehaviorFinding(kind=BehaviorKind.CROWD, track_count=5)
    assert set(crowd.magnitudes().keys()) == {"track_count"}

    # backend/events/rules.py:88-91 lee literalmente payload["duration_s"]: con otro
    # nombre (duration/dwell_s) duration_gte dejaria de disparar EN SILENCIO.
    assert "duration_s" in imm.magnitudes()
    assert "duration" not in imm.magnitudes()
    assert "dwell_s" not in imm.magnitudes()


# ─── Criterio 2 — aislamiento por trayectoria (igualdad de conjunto) ──────────
# ZONE_ENTERED/ZONE_EXITED se cubren en el plan 26-03 sobre
# EventEngine.process_zone, que es su unico dueño desde la Fase 19.

def TEST_trajectory_immobile_emits_only_immobile():
    analyzer = BehaviorAnalyzer()
    # 70 s (> immobile_secs=60, < loiter_secs=120): solo IMMOBILE puede disparar.
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=561, dt=0.125, amp=2.0)
    assert {f.kind for f in findings} == {BehaviorKind.IMMOBILE}


def TEST_trajectory_loiter_emits_only_loitering():
    analyzer = BehaviorAnalyzer()
    # amp=30 > immobile_radius_px=20: la caja envolvente se resetea cada frame,
    # IMMOBILE nunca acumula duracion. La distancia al ancla de LOITERING
    # (< loiter_radius_px=80) si se mantiene, y 130 s > loiter_secs=120.
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=261, dt=0.5, amp=30.0)
    assert {f.kind for f in findings} == {BehaviorKind.LOITERING}


def TEST_trajectory_running_emits_only_running():
    analyzer = BehaviorAnalyzer()
    history = _walk(0.0, 0.0, 400.0, 0.0, 2.0)
    t_now, x_now, y_now = history[-1]
    findings = analyzer.analyze({1: (x_now, y_now)}, {}, {1: history}, t_now)
    assert {f.kind for f in findings} == {BehaviorKind.RUNNING}


def TEST_trajectory_crowd_emits_only_crowd():
    analyzer = BehaviorAnalyzer(crowd_threshold=5)
    findings = analyzer.analyze({t: (1.0, 1.0) for t in range(5)}, {}, {}, 0.0)
    assert {f.kind for f in findings} == {BehaviorKind.CROWD}
