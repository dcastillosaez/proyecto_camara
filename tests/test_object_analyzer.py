"""Tests para ObjectAnalyzer (Fase 27, BEH-07).

Dominio puro: sin hilos, sin bus, sin reloj real. El reloj es un float
sintetico y las trayectorias son deterministas, mismo patron que
test_behavior_analyzer.py.
"""

from __future__ import annotations

from backend.perception.objects import (
    ObjectAnalyzer,
    ObjectFinding,
    ObjectKind,
    ObjectObservation,
    PersonObservation,
)


def _obj(tid=1, x=100.0, y=200.0, class_id=24, class_name="backpack",
         zone_id=None, excluded=False):
    return ObjectObservation(track_id=tid, x=x, y=y, class_id=class_id,
                             class_name=class_name, bbox=(x - 20, y - 40, x + 20, y),
                             zone_id=zone_id, excluded=excluded)


def _still_run(analyzer, n, dt=0.125, amp=2.0, start_t=20.0, persons=(), prime=True, **kw):
    """`n` frames de jitter ciclico de 3 fases (-amp, 0, +amp) alrededor del objeto.

    Ciclo de 3 fases igual que _jitter_run de test_behavior_analyzer.py: el
    desplazamiento entre fases consecutivas es `amp`, nunca `2*amp`, asi que el span
    de la caja envolvente se queda por debajo de still_radius_px.

    `prime=True` (por defecto) alimenta un frame vacio en t=0.0 ANTES de la
    trayectoria para fijar `_started_at` del analizador lejos de `start_t`
    (>= warmup_secs por defecto): el objeto de la trayectoria nace entonces
    como un track genuinamente nuevo, no como mobiliario del arranque
    (27-RESEARCH Q2). `TEST_warmup_furniture` es la unica excepcion:
    `prime=False` y `start_t=0.0` para probar justo el caso contrario.
    """
    if prime:
        analyzer.analyze([], [], 0.0)
    cx = kw.pop("x", 100.0)
    cy = kw.pop("y", 200.0)
    findings: list[ObjectFinding] = []
    for i in range(n):
        t = start_t + i * dt
        x = cx + amp * ((i % 3) - 1)
        obj = _obj(x=x, y=cy, **kw)
        if callable(persons):
            frame_persons = persons(i, t)
        else:
            frame_persons = list(persons)
        findings.extend(analyzer.analyze([obj], frame_persons, t))
    return findings


# ─── OBJECT_LEFT (criterio 2 del ROADMAP) ─────────────────────────────────────

def TEST_object_left_after_threshold():
    analyzer = ObjectAnalyzer()
    findings = _still_run(analyzer, n=561, dt=0.125, amp=2.0)
    left = [f for f in findings if f.kind is ObjectKind.LEFT]
    assert len(left) == 1
    assert left[0].duration_s > 60
    assert left[0].net_displacement_px <= 20


def TEST_object_left_latched():
    analyzer = ObjectAnalyzer()
    findings = _still_run(analyzer, n=1601, dt=0.125, amp=2.0)  # ~200 s
    left = [f for f in findings if f.kind is ObjectKind.LEFT]
    assert len(left) == 1


def TEST_object_left_only_kind():
    analyzer = ObjectAnalyzer()
    findings = _still_run(analyzer, n=561, dt=0.125, amp=2.0)
    assert {f.kind for f in findings} == {ObjectKind.LEFT}


# ─── Criterio 5 del ROADMAP: persona cerca suprime OBJECT_LEFT ────────────────
# La aserto es sobre el conjunto vacio (findings == []), no sobre la ausencia
# de un kind concreto: con una persona a 100 px en TODOS los frames el objeto
# nunca deberia producir ningun finding, ni siquiera de otro tipo.

def TEST_no_left_with_person():
    analyzer = ObjectAnalyzer()
    person = PersonObservation(track_id=99, x=100.0 + 100.0, y=200.0, height_px=300.0)
    findings = _still_run(analyzer, n=561, dt=0.125, amp=2.0, persons=[person])
    assert findings == []


def TEST_left_after_person_leaves():
    analyzer = ObjectAnalyzer()

    def persons(i, t):
        # Primeros 10 s de TRAYECTORIA (indice de frame, no tiempo absoluto:
        # la trayectoria nace en start_t, no en t=0).
        if i < 80:
            return [PersonObservation(track_id=99, x=200.0, y=200.0, height_px=300.0)]
        return []

    findings = _still_run(analyzer, n=561, dt=0.125, amp=2.0, persons=persons)
    left = [f for f in findings if f.kind is ObjectKind.LEFT]
    assert len(left) == 1
    # El LEFT solo se emite cuando han pasado left_secs desde la ultima vez
    # que hubo persona (t=10.0), nunca antes de left_secs desde el ancla.
    assert left[0].duration_s > analyzer._left_secs


# ─── Guarda de warmup: mobiliario fijo (27-RESEARCH Q2) ───────────────────────

def TEST_warmup_furniture():
    analyzer = ObjectAnalyzer()
    # Objeto presente desde el primer frame de vida del analizador (t=0, sin
    # priming): en el arranque, todo lo que esta en escena nace como track
    # nuevo y es indistinguible de algo que acaba de aparecer (27-RESEARCH
    # Q2) — la ventana de warmup es lo que separa "mobiliario" de
    # "abandonado".
    findings = _still_run(analyzer, n=1601, dt=0.125, amp=2.0, start_t=0.0, prime=False)
    assert findings == []
    assert 1 in analyzer._ignored


# ─── Guarda de zona de exclusion ───────────────────────────────────────────────

def TEST_excluded_zone():
    analyzer = ObjectAnalyzer()
    # `prime=True` (por defecto) fija el arranque del analizador en t=0 para
    # que el objeto, que nace a start_t=60, quede FUERA de la ventana de
    # warmup (10 s) y la guarda que se ejerza sea la de zona de exclusion,
    # no la de warmup.
    findings = _still_run(analyzer, n=1601, dt=0.125, amp=2.0, start_t=60.0, excluded=True)
    assert findings == []


# ─── OBJECT_REMOVED ─────────────────────────────────────────────────────────

def TEST_object_removed():
    analyzer = ObjectAnalyzer()
    # Objeto estable 30 s (> gone_secs) con una persona a 100 px en el ultimo frame.
    start_t = 20.0
    findings = _still_run(analyzer, n=241, dt=0.125, amp=2.0, start_t=start_t)  # 30 s
    assert findings == []
    last_t = start_t + 240 * 0.125
    person = PersonObservation(track_id=42, x=100.0 + 100.0, y=200.0, height_px=300.0)
    findings.extend(analyzer.analyze([_obj(x=100.0, y=200.0)], [person], last_t + 0.125))

    # El objeto deja de verse; prune tras la gracia de desaparicion decide REMOVED.
    now = last_t + 0.125 + analyzer._gone_secs + 0.1
    removed = analyzer.prune(now, seen_ids=set())
    assert len(removed) == 1
    assert removed[0].kind is ObjectKind.REMOVED
    assert removed[0].person_track_id == 42
    assert removed[0].person_distance_px is not None


def TEST_removed_needs_person():
    analyzer = ObjectAnalyzer()
    # Mismo escenario, pero sin ninguna persona en toda la vida del objeto.
    start_t = 20.0
    findings = _still_run(analyzer, n=241, dt=0.125, amp=2.0, start_t=start_t)  # 30 s
    assert findings == []
    last_t = start_t + 240 * 0.125
    now = last_t + analyzer._gone_secs + 0.1
    removed = analyzer.prune(now, seen_ids=set())
    assert removed == []
    assert 1 not in analyzer._aggs


# ─── Gracia de desaparicion (27-RESEARCH Pitfall 10) ──────────────────────────

def TEST_occlusion_grace():
    analyzer = ObjectAnalyzer()
    # Objeto estable que falta UN frame (0.125 s) y vuelve: sin gone_secs de
    # gracia, una oclusion de un solo frame (alguien pasa por delante)
    # emitiria OBJECT_REMOVED en silencio.
    start_t = 20.0
    findings = _still_run(analyzer, n=241, dt=0.125, amp=2.0, start_t=start_t)  # 30 s, estable
    assert findings == []
    last_t = start_t + 240 * 0.125
    missing_t = last_t + 0.125
    removed = analyzer.prune(missing_t, seen_ids=set())
    assert removed == []
    assert 1 in analyzer._aggs

    back_t = missing_t + 0.125
    findings.extend(analyzer.analyze([_obj(x=100.0, y=200.0)], [], back_t))
    assert findings == []
    assert 1 in analyzer._aggs


# ─── Payload sin None (criterio 3 del ROADMAP) ────────────────────────────────

def TEST_object_payload_has_no_none():
    left = ObjectFinding(kind=ObjectKind.LEFT, track_id=1, class_id=24,
                         class_name="backpack", bbox=(0, 0, 1, 1), zone_id=None,
                         duration_s=61.0, net_displacement_px=3.2)
    left_payload = left.magnitudes()
    assert None not in left_payload.values()
    assert "duration_s" in left_payload

    removed = ObjectFinding(kind=ObjectKind.REMOVED, track_id=1, class_id=24,
                            class_name="backpack", bbox=(0, 0, 1, 1),
                            duration_s=30.0, person_distance_px=90.0,
                            person_track_id=42)
    removed_payload = removed.magnitudes()
    assert None not in removed_payload.values()
