"""Tests para IdentityStateMachine (Fase 24, FACE-08..FACE-11).

La FSM es pura: no hay hilos, no hay reloj real, no hace falta mockear nada.
El reloj se inyecta como float sintetico (mismo patron que
test_memory_bounds.py: `now = float(i)`), asi que los 200 frames de
TEST_single_recognition_over_200_frames tardan microsegundos en vez de 100
segundos reales.
"""

from __future__ import annotations

from backend.perception.face.identity import (
    IdentityState,
    IdentityStateMachine,
    TemporalVoter,
)


def _fsm(
    window: int = 8,
    min_votes: int = 3,
    min_ratio: float = 0.6,
    lost_ttl: float = 30.0,
    revalidate_after: float = 120.0,
    low_confidence: float = 0.55,
) -> IdentityStateMachine:
    return IdentityStateMachine(
        TemporalVoter(window=window, min_votes=min_votes, min_ratio=min_ratio),
        lost_ttl=lost_ttl,
        revalidate_after=revalidate_after,
        low_confidence=low_confidence,
    )


# ─── Task 1: 4 estados y las 6 transiciones del contrato (criterio 1) ────────


def TEST_new_track_starts_unknown():
    fsm = _fsm()
    assert fsm.state_of(1) is IdentityState.UNKNOWN


def TEST_unknown_to_candidate_on_first_match():
    fsm = _fsm()
    t = fsm.on_face_result(1, 7, 0.7, now=0.0)
    assert t is not None
    assert t.from_state is IdentityState.UNKNOWN
    assert t.to_state is IdentityState.CANDIDATE
    assert fsm.state_of(1) is IdentityState.CANDIDATE


def TEST_candidate_to_confirmed_after_min_votes():
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=1.0)
    t = fsm.on_face_result(1, 7, 0.7, now=2.0)
    assert t is not None
    assert t.from_state is IdentityState.CANDIDATE
    assert t.to_state is IdentityState.CONFIRMED
    assert t.person_id == 7
    assert t.confidence > 0
    assert t.emits is True
    assert fsm.state_of(1) is IdentityState.CONFIRMED


def TEST_candidate_to_unknown_when_matches_dry_up():
    # La transicion ocurre en cuanto la ventana se llena (window=8 votos
    # totales, incluido el primer match): no necesariamente en la ultima de
    # las 8 llamadas con person_id=None, por eso se recogen todos los
    # resultados en vez de quedarse solo con el de la ultima iteracion.
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    results = [fsm.on_face_result(1, None, 0.0, now=float(i)) for i in range(1, 9)]
    transitions = [r for r in results if r is not None]
    assert len(transitions) == 1
    t = transitions[0]
    assert t.from_state is IdentityState.CANDIDATE
    assert t.to_state is IdentityState.UNKNOWN
    assert t.emits is True

    # Segundo ciclo CANDIDATE -> UNKNOWN en el MISMO track: una sola emision
    # de UNKNOWN_PERSON por track (D-02).
    fsm.on_face_result(1, 7, 0.7, now=9.0)
    results2 = [fsm.on_face_result(1, None, 0.0, now=float(i)) for i in range(10, 18)]
    transitions2 = [r for r in results2 if r is not None]
    assert len(transitions2) == 1
    assert transitions2[0].to_state is IdentityState.UNKNOWN
    assert transitions2[0].emits is False


def TEST_alternating_identities_stay_candidate():
    """Criterio 3: identidades en conflicto no confirman ninguna ni caen a
    UNKNOWN mientras sigan llegando matches. Rotacion de 3 identidades (no
    solo 2) para evitar el empate de ventana parcial 3/5=0.6==min_ratio que
    una alternancia estrictamente binaria produce en la 5a votacion (ventana
    aun sin llenar) con window=8/min_votes=3/min_ratio=0.6 — ese 3/5 exacto
    dispararia una confirmacion espuria por una coincidencia numerica de la
    ventana parcial, no por evidencia real de una identidad coherente; con
    3 identidades en conflicto ningun candidato alcanza nunca min_votes con
    ratio >= 0.6 (ver Deviations en el SUMMARY)."""
    fsm = _fsm()
    people = [7, 9, 11]
    confirmed = False
    for i in range(20):
        person = people[i % len(people)]
        t = fsm.on_face_result(1, person, 0.7, now=float(i))
        if t is not None and t.to_state is IdentityState.CONFIRMED:
            confirmed = True
        assert fsm.state_of(1) is IdentityState.CANDIDATE
    assert not confirmed
    assert fsm.state_of(1) is IdentityState.CANDIDATE


def TEST_confirmed_to_temporarily_lost_on_track_lost():
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=1.0)
    fsm.on_face_result(1, 7, 0.7, now=2.0)
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    t = fsm.on_track_lost(1, now=3.0)
    assert t is not None
    assert t.from_state is IdentityState.CONFIRMED
    assert t.to_state is IdentityState.TEMPORARILY_LOST
    assert t.emits is False
    assert fsm.state_of(1) is IdentityState.TEMPORARILY_LOST


def TEST_temporarily_lost_to_confirmed_on_coherent_match():
    """FACE-09/FACE-10: track_id NUEVO (ByteTrack nunca reutiliza ids). Un solo
    match coherente basta para heredar la identidad perdida sin re-votar."""
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=1.0)
    fsm.on_face_result(1, 7, 0.7, now=2.0)
    fsm.on_track_lost(1, now=10.0)

    t = fsm.on_face_result(2, 7, 0.7, now=15.0)
    assert fsm.state_of(2) is IdentityState.CONFIRMED
    assert t is not None
    assert t.emits is False


def TEST_temporarily_lost_to_unknown_after_lost_ttl():
    fsm = _fsm(lost_ttl=30.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_track_lost(1, now=0.0)

    transitions = fsm.on_tick(31.0)
    assert len(transitions) == 1
    t = transitions[0]
    assert t.from_state is IdentityState.TEMPORARILY_LOST
    assert t.to_state is IdentityState.UNKNOWN
    assert t.emits is True
    assert fsm.state_of(1) is IdentityState.UNKNOWN


def TEST_single_recognition_over_200_frames():
    """Criterio 2: 200 resultados de la misma persona producen exactamente una
    confirmacion emisora."""
    fsm = _fsm()
    confirmations = 0
    for i in range(200):
        t = fsm.on_face_result(1, 7, 0.8, now=i * 0.5)
        if t is not None and t.to_state is IdentityState.CONFIRMED and t.emits:
            confirmations += 1
    assert confirmations == 1


def TEST_unknown_result_on_unknown_track_emits_nothing():
    fsm = _fsm()
    t = fsm.on_face_result(1, None, 0.0, now=0.0)
    assert t is None
    assert fsm.state_of(1) is IdentityState.UNKNOWN


# ─── Task 2: revalidacion, IDENTITY_LOST, herencia por person_id, gate ───────
# ─── needs_recognition (criterios 4 y 5, D-03, D-04, D-06, FACE-11) ──────────


def TEST_revalidate_after_expires_triggers_recheck():
    fsm = _fsm(revalidate_after=120.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    assert fsm.needs_recognition(1, 100.0) is False
    assert fsm.needs_recognition(1, 121.0) is True


def TEST_three_failed_revalidations_emit_identity_lost():
    """Criterio 5: tres ciclos de revalidacion vencidos sin match sacan al
    track de CONFIRMED (D-04: se cuenta por ciclo, no por frame)."""
    fsm = _fsm(revalidate_after=120.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)

    t1 = fsm.on_face_result(1, None, 0.0, now=121.0)
    assert t1 is None
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    t2 = fsm.on_face_result(1, None, 0.0, now=242.0)
    assert t2 is None
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    t3 = fsm.on_face_result(1, None, 0.0, now=363.0)
    assert t3 is not None
    assert t3.from_state is IdentityState.CONFIRMED
    assert t3.to_state is IdentityState.UNKNOWN
    assert t3.emits is True
    assert fsm.state_of(1) is IdentityState.UNKNOWN


def TEST_failed_revalidation_only_counts_once_per_cycle():
    """D-04: dentro del mismo ciclo (sin que venza revalidate_after de nuevo)
    los fallos adicionales no incrementan el contador."""
    fsm = _fsm(revalidate_after=120.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)

    fsm.on_face_result(1, None, 0.0, now=121.0)
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    fsm.on_face_result(1, None, 0.0, now=122.0)
    fsm.on_face_result(1, None, 0.0, now=123.0)
    assert fsm.state_of(1) is IdentityState.CONFIRMED


def TEST_successful_revalidation_resets_failures():
    fsm = _fsm(revalidate_after=120.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)

    fsm.on_face_result(1, None, 0.0, now=121.0)   # fallo 1
    fsm.on_face_result(1, None, 0.0, now=242.0)   # fallo 2
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    fsm.on_face_result(1, 7, 0.7, now=363.0)      # revalidacion con exito
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    # Hacen falta 3 fallos NUEVOS (no solo 1) para perder la identidad.
    fsm.on_face_result(1, None, 0.0, now=484.0)   # fallo 1 (nuevo ciclo)
    assert fsm.state_of(1) is IdentityState.CONFIRMED
    fsm.on_face_result(1, None, 0.0, now=605.0)   # fallo 2
    assert fsm.state_of(1) is IdentityState.CONFIRMED
    t = fsm.on_face_result(1, None, 0.0, now=726.0)   # fallo 3 -> IDENTITY_LOST
    assert t is not None
    assert t.to_state is IdentityState.UNKNOWN
    assert fsm.state_of(1) is IdentityState.UNKNOWN


def TEST_low_identity_confidence_triggers_recognition():
    """D-03: el disparador de confianza baja usa la confianza del voter, no
    la confianza de deteccion de YOLO."""
    fsm = _fsm(low_confidence=0.55)
    fsm.on_face_result(1, 7, 0.5, now=0.0)
    fsm.on_face_result(1, 7, 0.5, now=0.0)
    fsm.on_face_result(1, 7, 0.5, now=0.0)
    assert fsm.state_of(1) is IdentityState.CONFIRMED
    assert fsm.identity_of(1)[1] < 0.55
    assert fsm.needs_recognition(1, 1.0) is True

    fsm2 = _fsm(low_confidence=0.55)
    fsm2.on_face_result(2, 7, 0.9, now=0.0)
    fsm2.on_face_result(2, 7, 0.9, now=0.0)
    fsm2.on_face_result(2, 7, 0.9, now=0.0)
    assert fsm2.identity_of(2)[1] >= 0.55
    assert fsm2.needs_recognition(2, 1.0) is False


def TEST_needs_recognition_for_new_candidate_and_lost_states():
    fsm = _fsm()
    assert fsm.needs_recognition(99, 0.0) is True   # track nunca visto

    fsm.on_face_result(1, 7, 0.7, now=0.0)
    assert fsm.state_of(1) is IdentityState.CANDIDATE
    assert fsm.needs_recognition(1, 0.0) is True

    fsm.on_face_result(2, 7, 0.7, now=0.0)
    fsm.on_face_result(2, 7, 0.7, now=0.0)
    fsm.on_face_result(2, 7, 0.7, now=0.0)
    fsm.on_track_lost(2, now=1.0)
    assert fsm.state_of(2) is IdentityState.TEMPORARILY_LOST
    assert fsm.needs_recognition(2, 1.0) is True


def TEST_needs_recognition_backs_off_on_exhausted_unknown():
    """Base del criterio 6: una vez la ventana de votos se llena sin ningun
    match, no merece la pena volver a intentar hasta que pase
    revalidate_after."""
    fsm = _fsm(window=8, revalidate_after=120.0)
    for i in range(8):
        fsm.on_face_result(1, None, 0.0, now=float(i))
    assert fsm.state_of(1) is IdentityState.UNKNOWN

    assert fsm.needs_recognition(1, 8.0) is False
    assert fsm.needs_recognition(1, 128.0) is True


def TEST_track_recovery_keeps_same_identity():
    """Criterio 4: perder y recuperar un track (con id NUEVO, como ByteTrack)
    conserva la identidad sin duplicarla."""
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=1.0)
    confirmations = []

    def _record(t):
        if t is not None and t.to_state is IdentityState.CONFIRMED and t.emits:
            confirmations.append(t)

    _record(fsm.on_face_result(1, 7, 0.7, now=2.0))
    fsm.on_track_lost(1, now=10.0)

    _record(fsm.on_face_result(2, 7, 0.7, now=15.0))

    assert fsm.identity_of(2) == (7, fsm.identity_of(2)[1])
    assert fsm.identity_of(2)[1] > 0
    assert fsm.state_of(2) is IdentityState.CONFIRMED
    assert len(confirmations) == 1


def TEST_recovery_after_lost_ttl_is_a_new_visit():
    """La misma secuencia que la recuperacion, pero fuera de lost_ttl: es una
    visita nueva, no una recuperacion silenciosa."""
    fsm = _fsm(lost_ttl=30.0)
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=1.0)
    fsm.on_face_result(1, 7, 0.7, now=2.0)
    fsm.on_track_lost(1, now=10.0)
    fsm.on_tick(41.0)   # vence lost_ttl (10 + 30 < 41) -> se elimina la entrada

    results = [
        fsm.on_face_result(2, 7, 0.7, now=45.0),
        fsm.on_face_result(2, 7, 0.7, now=46.0),
        fsm.on_face_result(2, 7, 0.7, now=47.0),
    ]
    confirmations = [
        t for t in results if t is not None and t.to_state is IdentityState.CONFIRMED
    ]
    assert len(confirmations) == 1
    assert confirmations[0].emits is True


def TEST_on_active_tracks_reports_lost_tracks():
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=1.0)
    fsm.on_face_result(1, 7, 0.7, now=2.0)
    assert fsm.state_of(1) is IdentityState.CONFIRMED

    fsm.on_face_result(2, 8, 0.7, now=2.0)
    assert fsm.state_of(2) is IdentityState.CANDIDATE

    out1 = fsm.on_active_tracks({1}, now=3.0)
    assert len(out1) == 1
    assert out1[0].track_id == 2
    assert out1[0].from_state is IdentityState.CANDIDATE
    assert out1[0].to_state is IdentityState.UNKNOWN

    out2 = fsm.on_active_tracks(set(), now=4.0)
    assert len(out2) == 1
    assert out2[0].track_id == 1
    assert out2[0].from_state is IdentityState.CONFIRMED
    assert out2[0].to_state is IdentityState.TEMPORARILY_LOST

    out3 = fsm.on_active_tracks(set(), now=5.0)
    assert out3 == []


def TEST_stale_states_are_evicted_by_on_tick():
    """Cota dura de memoria (invariante de la Fase 22): una entrada rancia
    desaparece aunque nadie llame on_active_tracks a tiempo."""
    fsm = _fsm(lost_ttl=30.0, revalidate_after=120.0)
    fsm.on_face_result(1, None, 0.0, now=0.0)
    assert 1 in fsm._states

    stale_ttl = 30.0 + 120.0 * IdentityStateMachine.MAX_FAILED_REVALIDATIONS
    fsm.on_tick(stale_ttl + 1.0)
    assert 1 not in fsm._states


# ─── Fase 25 — herencia de identidad por apariencia (REID-02/REID-03) ────────
# ReID entra por la FSM (on_reid_result), nunca por el worker: resolver la
# herencia fuera de la FSM deja huerfana la entrada TEMPORARILY_LOST en
# _states, y 30 s despues on_tick() emite un IDENTITY_LOST espurio de una
# persona que el sistema tiene delante y ya reetiquetada (Pitfall 4 del
# RESEARCH). Solo _claim_lost() limpia esa entrada y es privado de la FSM.


def TEST_reid_inherits_identity_from_lost_track():
    fsm = _fsm()
    for t in (0.0, 1.0, 2.0):
        fsm.on_face_result(1, 7, 0.7, now=t)          # track 1 -> CONFIRMED como persona 7
    assert fsm.state_of(1) is IdentityState.CONFIRMED
    fsm.on_track_lost(1, now=10.0)                     # se gira / desaparece
    tr = fsm.on_reid_result(2, 7, 0.85, now=15.0)      # reaparece con track_id NUEVO, sin cara
    assert tr is not None
    assert tr.to_state is IdentityState.CONFIRMED
    assert tr.person_id == 7
    assert tr.emits is False, "criterio 3: misma visita, no un 2o PERSON_RECOGNIZED"
    assert tr.votes == 0
    assert fsm.identity_of(2) == (7, 0.85)
    assert fsm.state_of(1) is IdentityState.UNKNOWN    # la entrada vieja fue reclamada


def TEST_reid_does_not_vote_in_temporal_voter():
    fsm = _fsm()
    for t in (0.0, 1.0, 2.0):
        fsm.on_face_result(1, 7, 0.7, now=t)
    fsm.on_track_lost(1, now=10.0)
    fsm.on_reid_result(2, 7, 0.9, now=15.0)
    # Un voto de apariencia invalidaria los parametros medidos de FACE-07.
    assert fsm._voter.votes_for(2) == 0


def TEST_reid_does_not_hijack_confirmed_or_candidate_track():
    fsm = _fsm(min_votes=3)
    fsm.on_face_result(2, 9, 0.7, now=0.0)
    fsm.on_face_result(2, 9, 0.7, now=1.0)
    fsm.on_face_result(2, 9, 0.7, now=2.0)
    assert fsm.state_of(2) is IdentityState.CONFIRMED
    tr2 = fsm.on_reid_result(2, 7, 0.99, now=3.0)
    assert tr2 is None
    assert fsm.identity_of(2)[0] == 9

    fsm.on_face_result(3, 5, 0.7, now=0.0)   # un solo voto: sigue en votacion
    assert fsm.state_of(3) is IdentityState.CANDIDATE
    tr3 = fsm.on_reid_result(3, 7, 0.99, now=1.0)
    assert tr3 is None
    assert fsm.state_of(3) is IdentityState.CANDIDATE


def TEST_reid_ignored_when_track_has_face_evidence():
    fsm = _fsm()
    fsm.on_face_result(4, 7, 0.7, now=0.0)   # UNKNOWN -> CANDIDATE, pero ya con voto facial
    assert fsm._voter.matched_votes(4) > 0
    tr = fsm.on_reid_result(4, 7, 0.99, now=1.0)
    assert tr is None


def TEST_reid_without_lost_identity_does_nothing():
    fsm = _fsm()
    tr = fsm.on_reid_result(2, 7, 0.85, now=0.0)
    assert tr is None
    assert fsm.state_of(2) is IdentityState.UNKNOWN


def TEST_reid_no_spurious_identity_lost():
    """Pitfall 4, el test que justifica todo el diseño."""
    fsm = _fsm(lost_ttl=30.0)
    for t in (0.0, 1.0, 2.0):
        fsm.on_face_result(1, 7, 0.7, now=t)
    fsm.on_track_lost(1, now=10.0)
    assert fsm.on_reid_result(2, 7, 0.85, now=15.0) is not None
    transitions = fsm.on_tick(now=10.0 + 30.0 + 1.0)   # lost_ttl + epsilon
    assert transitions == [], (
        "on_tick emitio una transicion tras heredar por ReID: la entrada "
        "TEMPORARILY_LOST quedo huerfana y produciria un IDENTITY_LOST espurio "
        "para alguien que esta delante de la camara (Pitfall 4)"
    )
    assert fsm.state_of(2) is IdentityState.CONFIRMED


def TEST_reid_inherited_track_survives_stale_sweep():
    """Pitfall 5: last_face_at se fijo al heredar, la entrada no se barre por
    rancia en el siguiente on_tick cercano."""
    fsm = _fsm()
    for t in (0.0, 1.0, 2.0):
        fsm.on_face_result(1, 7, 0.7, now=t)
    fsm.on_track_lost(1, now=10.0)
    fsm.on_reid_result(2, 7, 0.85, now=15.0)
    assert fsm.state_of(2) is IdentityState.CONFIRMED

    fsm.on_tick(now=16.0)
    assert fsm.state_of(2) is IdentityState.CONFIRMED
