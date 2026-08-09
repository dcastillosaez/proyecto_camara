"""Tests for backend.perception.face.index.IdentityIndex — search + latency budget."""

from __future__ import annotations

import time

import numpy as np
import pytest

from backend.perception.face.index import IdentityIndex


def _random_unit_vec(rng: np.random.Generator, dim: int = 512) -> np.ndarray:
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def TEST_empty_index_search_returns_empty():
    index = IdentityIndex()
    rng = np.random.default_rng(0)
    assert index.search(_random_unit_vec(rng)) == []


def TEST_add_and_search_finds_exact_match():
    index = IdentityIndex()
    rng = np.random.default_rng(1)
    emb = _random_unit_vec(rng)
    index.add(person_id=42, emb=emb)

    results = index.search(emb, top_k=1)
    assert results[0][0] == 42
    assert results[0][1] == pytest.approx(1.0, abs=1e-5)


def TEST_search_ranks_by_similarity():
    rng = np.random.default_rng(2)
    index = IdentityIndex()
    base = _random_unit_vec(rng)
    # A near-duplicate of `base` (small perturbation, re-normalized) and two
    # unrelated random vectors.
    near = base + 0.05 * _random_unit_vec(rng)
    near = near / np.linalg.norm(near)
    far_a = _random_unit_vec(rng)
    far_b = _random_unit_vec(rng)

    index.add(person_id=1, emb=near)
    index.add(person_id=2, emb=far_a)
    index.add(person_id=3, emb=far_b)

    results = index.search(base, top_k=3)
    assert results[0][0] == 1
    assert results[0][1] > results[1][1] >= results[2][1] or results[0][1] > results[1][1]


def TEST_search_on_1000_identities_under_5ms():
    rng = np.random.default_rng(3)
    index = IdentityIndex()
    for pid in range(1000):
        index.add(person_id=pid, emb=_random_unit_vec(rng))

    query = _random_unit_vec(rng)
    durations = []
    for _ in range(100):
        t0 = time.perf_counter()
        index.search(query, top_k=3)
        durations.append(time.perf_counter() - t0)

    p95 = float(np.percentile(durations, 95))
    assert p95 < 0.005, f"p95 search latency {p95 * 1000:.2f}ms exceeds 5ms budget"


def TEST_rebuild_reflects_removed_or_updated_entries():
    rng = np.random.default_rng(4)
    index = IdentityIndex()
    index.add(person_id=1, emb=_random_unit_vec(rng))
    index.add(person_id=2, emb=_random_unit_vec(rng))

    new_emb_for_2 = _random_unit_vec(rng)
    index.rebuild([(2, new_emb_for_2)])  # person 1 dropped, person 2 re-embedded

    results = index.search(new_emb_for_2, top_k=5)
    ids = [pid for pid, _ in results]
    assert 1 not in ids
    assert ids[0] == 2
