"""Tests para TrackGallery (Fase 25, REID-02/REID-04).

La galeria es dominio puro: no hay hilos, no hay reloj real, no hay ONNX. El
reloj se inyecta como float sintetico, igual que en test_identity_state_machine.py.

NUNCA usar el generador aleatorio de numpy como "embedding de persona": el
research de la Fase 25 midio que el coseno entre dos embeddings de OSNet
alimentados con ruido independiente sale 0,991 (colapso fuera de distribucion).
Un test asi "demostraria" que todo se parece a todo y no probaria nada sobre el
umbral de 0,7. Aqui los vectores se construyen a mano con coseno EXACTO y
controlado.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.perception.reid.gallery import TrackGallery

DIM = 512


def _gallery(inherit_window=15.0, similarity_threshold=0.7, interval=2.0,
             max_entries=256) -> TrackGallery:
    return TrackGallery(inherit_window=inherit_window,
                        similarity_threshold=similarity_threshold,
                        interval=interval, max_entries=max_entries)


def _vec(i: int) -> np.ndarray:
    """Vector base ortonormal i: coseno 0 con cualquier _vec(j != i)."""
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def _vec_at_cosine(base_index: int, cos: float, other_index: int = 511) -> np.ndarray:
    """Vector unitario cuyo coseno con _vec(base_index) es EXACTAMENTE `cos`.

    cos * e_base + sqrt(1 - cos^2) * e_other, con e_base perpendicular a e_other.
    """
    v = np.zeros(DIM, dtype=np.float32)
    v[base_index] = cos
    v[other_index] = float(np.sqrt(1.0 - cos * cos))
    return v


# ─── Criterio 2: herencia dentro de ventana y por encima del umbral ──────────


def TEST_gallery_inherits_identity_within_window_above_threshold():
    gallery = _gallery()
    gallery.update(1, _vec(0), 7, now=0.0)

    pid, sim = gallery.resolve(2, _vec_at_cosine(0, 0.95), now=5.0, active_identities=set())

    assert pid == 7
    assert sim == pytest.approx(0.95, abs=1e-4)


def TEST_gallery_does_not_inherit_below_threshold():
    gallery = _gallery()
    gallery.update(1, _vec(0), 7, now=0.0)

    pid, sim = gallery.resolve(2, _vec_at_cosine(0, 0.65), now=5.0, active_identities=set())

    # La similitud se devuelve IGUALMENTE: es el dato de auditoria del criterio 4.
    assert pid is None
    assert sim == pytest.approx(0.65, abs=1e-4)


def TEST_gallery_does_not_inherit_at_exactly_threshold():
    gallery = _gallery()
    gallery.update(1, _vec(0), 7, now=0.0)

    # Criterio 2: "similitud > 0.7" es un umbral ESTRICTO, 0.70 exacto no hereda.
    pid, _sim = gallery.resolve(2, _vec_at_cosine(0, 0.70), now=5.0, active_identities=set())

    assert pid is None


def TEST_gallery_does_not_inherit_outside_window():
    gallery = _gallery(inherit_window=15.0)
    gallery.update(1, _vec(0), 7, now=0.0)

    pid, _sim = gallery.resolve(2, _vec_at_cosine(0, 0.95), now=16.0, active_identities=set())

    assert pid is None


def TEST_gallery_conflict_with_active_identity_blocks_inherit():
    gallery = _gallery()
    gallery.update(1, _vec(0), 7, now=0.0)

    pid, sim = gallery.resolve(2, _vec_at_cosine(0, 0.95), now=5.0, active_identities={7})

    # Esto es lo que impide fusionar dos personas cuando la "perdida" en
    # realidad sigue en pantalla: la persona 7 sigue visible en otro track.
    assert pid is None
    assert sim == pytest.approx(0.95, abs=1e-4)


# ─── Criterio 4: dos apariencias distintas no se fusionan ───────────────────


def TEST_gallery_does_not_merge_two_different_appearances():
    gallery = _gallery()
    gallery.update(1, _vec(0), 7, now=0.0)
    gallery.update(2, _vec(1), 9, now=0.0)

    pid_a, _sim_a = gallery.resolve(3, _vec_at_cosine(0, 0.98), now=1.0, active_identities=set())
    pid_b, _sim_b = gallery.resolve(4, _vec_at_cosine(1, 0.30), now=1.0, active_identities=set())

    assert pid_a == 7, "dos personas distintas con ropa similar no se fusionan (criterio 4)"
    assert pid_b is None, "dos personas distintas con ropa similar no se fusionan (criterio 4)"


# ─── Casos limite de resolve() ───────────────────────────────────────────────


def TEST_gallery_ignores_entries_without_identity():
    gallery = _gallery()
    gallery.update(1, _vec(0), None, now=0.0)

    pid, sim = gallery.resolve(2, _vec_at_cosine(0, 0.99), now=1.0, active_identities=set())

    assert (pid, sim) == (None, 0.0)


def TEST_gallery_does_not_resolve_against_itself():
    gallery = _gallery()
    gallery.update(1, _vec(0), 7, now=0.0)

    pid, sim = gallery.resolve(1, _vec(0), now=1.0, active_identities=set())

    assert (pid, sim) == (None, 0.0)


# ─── Criterio 5: intervalo minimo entre re-embeddings ────────────────────────


def TEST_gallery_needs_embedding_respects_interval():
    gallery = _gallery(interval=2.0)

    assert gallery.needs_embedding(1, 0.0) is True

    gallery.update(1, _vec(0), None, now=0.0)

    assert gallery.needs_embedding(1, 1.9) is False
    assert gallery.needs_embedding(1, 2.0) is True


# ─── Expiracion (doble guarda) ───────────────────────────────────────────────


def TEST_gallery_prune_drops_entries_older_than_window():
    gallery = _gallery(inherit_window=15.0)
    gallery.update(1, _vec(0), 7, now=0.0)
    gallery.update(2, _vec(1), 8, now=10.0)
    gallery.update(3, _vec(2), 9, now=19.0)

    gallery.prune(now=20.0, frame_ids=set())

    assert 1 not in gallery._entries
    assert 2 in gallery._entries
    assert 3 in gallery._entries


def TEST_gallery_prune_keeps_tracks_present_in_frame():
    gallery = _gallery(inherit_window=15.0)
    gallery.update(1, _vec(0), 7, now=0.0)

    # El track sigue delante de la camara aunque aun no le toque re-embeber.
    gallery.prune(now=20.0, frame_ids={1})

    assert 1 in gallery._entries


def TEST_gallery_embeddings_are_float32():
    gallery = _gallery()
    gallery.update(1, np.ones(512, dtype=np.float64) / np.sqrt(512), 7, now=0.0)

    assert gallery._entries[1].emb.dtype == np.float32
