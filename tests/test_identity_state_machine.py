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
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    t = None
    for i in range(1, 9):
        t = fsm.on_face_result(1, None, 0.0, now=float(i))
    assert t is not None
    assert t.from_state is IdentityState.CANDIDATE
    assert t.to_state is IdentityState.UNKNOWN
    assert t.emits is True

    # Segundo ciclo CANDIDATE -> UNKNOWN en el MISMO track: una sola emision
    # de UNKNOWN_PERSON por track (D-02).
    fsm.on_face_result(1, 7, 0.7, now=9.0)
    t2 = None
    for i in range(10, 18):
        t2 = fsm.on_face_result(1, None, 0.0, now=float(i))
    assert t2 is not None
    assert t2.to_state is IdentityState.UNKNOWN
    assert t2.emits is False


def TEST_alternating_identities_stay_candidate():
    """Criterio 3: identidades alternadas no confirman ninguna ni caen a UNKNOWN
    mientras sigan llegando matches (en conflicto)."""
    fsm = _fsm()
    confirmed = False
    for i in range(20):
        person = 7 if i % 2 == 0 else 9
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
