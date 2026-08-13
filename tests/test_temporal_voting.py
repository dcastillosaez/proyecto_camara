"""Tests for backend.perception.face.identity.TemporalVoter (Fase 24 — FACE-07).

TemporalVoter es dominio puro (sin reloj, sin hilos, sin I/O): estos tests lo
ejercitan directamente, sin mocks, votando resultados sintéticos y comprobando
el veredicto agregado.
"""

from __future__ import annotations

import pytest

from backend.perception.face.identity import TemporalVoter


# ─── Track sin votos no tiene veredicto ────────────────────────────────────────
def TEST_verdict_empty_track_returns_none():
    """Un track sin votos previos devuelve (None, 0.0)."""
    voter = TemporalVoter()
    assert voter.verdict(1) == (None, 0.0)


# ─── El veredicto requiere el minimo de votos coherentes ──────────────────────
def TEST_verdict_needs_min_votes():
    """Con min_votes=3, hacen falta 3 votos coherentes antes de que haya ganador."""
    voter = TemporalVoter(window=8, min_votes=3, min_ratio=0.6)
    voter.vote(1, 7, 0.9)
    voter.vote(1, 7, 0.9)
    assert voter.verdict(1) == (None, 0.0)
    voter.vote(1, 7, 0.9)
    person_id, score = voter.verdict(1)
    assert person_id == 7
    assert score > 0


# ─── La confianza agregada es la media de los scores del ganador ──────────────
def TEST_verdict_aggregates_confidence():
    """La confianza agregada es la media de los scores del ganador, no el máximo."""
    voter = TemporalVoter(window=8, min_votes=3, min_ratio=0.6)
    voter.vote(1, 7, 0.6)
    voter.vote(1, 7, 0.8)
    voter.vote(1, 7, 0.7)
    assert voter.verdict(1)[1] == pytest.approx(0.7)


# ─── Criterio 3 de la fase: identidades alternadas sin ganador ────────────────
def TEST_alternating_identities_have_no_winner():
    """A,B,A,B,... con window=8 da 4/8=0.5 < min_ratio=0.6: no hay ganador."""
    voter = TemporalVoter(window=8, min_votes=3, min_ratio=0.6)
    for i in range(8):
        person_id = 7 if i % 2 == 0 else 8
        voter.vote(1, person_id, 0.9)
    assert voter.verdict(1) == (None, 0.0)
    assert voter.matched_votes(1) == 8


# ─── El ratio cuenta tambien los votos sin match (None) ───────────────────────
def TEST_ratio_counts_unmatched_votes():
    """3 votos a la persona 7 y 5 votos None: 3/8=0.375 < 0.6, sin ganador."""
    voter = TemporalVoter(window=8, min_votes=3, min_ratio=0.6)
    for _ in range(3):
        voter.vote(1, 7, 0.9)
    for _ in range(5):
        voter.vote(1, None, 0.0)
    assert voter.verdict(1) == (None, 0.0)


# ─── La ventana desliza acotada por maxlen ─────────────────────────────────────
def TEST_window_is_sliding():
    """Votar mas veces que `window` no crece la ventana: la acota deque(maxlen=)."""
    voter = TemporalVoter(window=8, min_votes=3, min_ratio=0.6)
    for _ in range(20):
        voter.vote(1, 7, 0.9)
    assert len(voter._votes[1]) == 8


# ─── reset() limpia el estado de un track ──────────────────────────────────────
def TEST_reset_clears_track():
    """Tras reset(tid), el track vuelve a no tener veredicto ni votos."""
    voter = TemporalVoter(window=8, min_votes=3, min_ratio=0.6)
    for _ in range(3):
        voter.vote(1, 7, 0.9)
    voter.reset(1)
    assert voter.verdict(1) == (None, 0.0)
    assert voter.votes_for(1) == 0


# ─── prune() elimina tracks que ya no estan activos ───────────────────────────
def TEST_prune_drops_inactive_tracks():
    """prune(active_track_ids) borra las entradas de tracks fuera del conjunto activo."""
    voter = TemporalVoter(window=8, min_votes=3, min_ratio=0.6)
    for tid in range(1, 101):
        voter.vote(tid, 7, 0.9)
    voter.prune({98, 99})
    assert len(voter._votes) == 2
