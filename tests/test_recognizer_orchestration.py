"""Tests for backend.recognizer.PersonRecognizer orchestration (Fase 23).

PersonRecognizer no longer calls face_recognition/dlib directly — it
delegates to backend.perception.face.{engine,quality,index}. These tests
mock FaceEngine/FaceQualityAssessor (patched at construction time, so
PersonRecognizer never loads a real ONNX model) and exercise the same
business logic the dlib-era tests in test_phase9.py used to cover:
consensus buffering, ratio-test ambiguity, same-person-multiple-samples
grouping, and majority-vote re-verification — see that file's history for
the original (now superseded) dlib-based versions.

backend.perception.face.index.IdentityIndex is NOT mocked: it's simple,
deterministic, and exercising the real cosine-similarity math end-to-end
is more meaningful than mocking it too.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import numpy as np

from backend.perception.face.engine import FaceCandidate
from backend.perception.face.quality import FaceQuality
from backend.recognizer import PersonRecognizer

_DIM = 512


def _unit_vec(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _at_similarity(base: np.ndarray, similarity: float, seed: int) -> np.ndarray:
    """A unit vector with cosine similarity ~*similarity* to *base*."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(_DIM).astype(np.float32)
    noise -= np.dot(noise, base) * base
    noise /= np.linalg.norm(noise)
    result = similarity * base + np.sqrt(max(0.0, 1 - similarity**2)) * noise
    return (result / np.linalg.norm(result)).astype(np.float32)


def _cand(bbox: tuple[int, int, int, int] = (0, 0, 80, 80)) -> FaceCandidate:
    kps = np.array([[20, 20], [60, 20], [40, 40], [25, 60], [55, 60]], dtype=np.float32)
    return FaceCandidate(bbox=bbox, kps=kps, det_score=0.9)


def _passing_quality() -> FaceQuality:
    return FaceQuality(
        size_px=80, blur=500.0, yaw=0.0, pitch=0.0, roll=0.0,
        brightness=128.0, passed=True, reason=None,
    )


def _failing_quality(reason: str = "blurry") -> FaceQuality:
    return FaceQuality(
        size_px=80, blur=1.0, yaw=0.0, pitch=0.0, roll=0.0,
        brightness=128.0, passed=False, reason=reason,
    )


def _make_recognizer(tmp_path, available: bool = True) -> tuple[PersonRecognizer, MagicMock, MagicMock]:
    """A PersonRecognizer wired to mock FaceEngine/FaceQualityAssessor, with a real IdentityIndex."""
    engine = MagicMock()
    engine.available = available
    quality = MagicMock()
    quality.assess.return_value = _passing_quality()
    with (
        patch("backend.recognizer.FaceEngine", return_value=engine),
        patch("backend.recognizer.FaceQualityAssessor", return_value=quality),
    ):
        r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    return r, engine, quality


_FAKE_FRAME = np.zeros((200, 200, 3), dtype=np.uint8)


# ─── available refleja FaceEngine.available ──────────────────────────────────
def TEST_available_reflects_engine_availability(tmp_path):
    r, _, _ = _make_recognizer(tmp_path, available=False)
    assert r.available is False


# ─── Contrato público sin cambios (lo que consume RecognitionWorker) ─────────
def TEST_public_contract_unchanged(tmp_path):
    r, _, _ = _make_recognizer(tmp_path)
    assert list(inspect.signature(r.process_crop).parameters) == ["crop_bgr", "tracker_id"]
    assert list(inspect.signature(r.prune).parameters) == ["active_tracker_ids"]
    assert callable(r.available.__eq__)  # property access doesn't raise
    assert list(inspect.signature(r.list_persons).parameters) == []
    assert list(inspect.signature(r.enroll_named_face).parameters) == ["image_bgr", "name"]


# ─── Sin cara detectada: no llega a evaluar calidad ni a embeber ─────────────
def TEST_process_crop_no_face_detected(tmp_path):
    r, engine, quality = _make_recognizer(tmp_path)
    engine.detect.return_value = []

    result = r.process_crop(_FAKE_FRAME, tracker_id=1)

    assert result == (None, None, False)
    quality.assess.assert_not_called()
    engine.embed.assert_not_called()


# ─── Cara de baja calidad se descarta sin generar embedding ──────────────────
def TEST_process_crop_rejects_low_quality_face(tmp_path):
    r, engine, quality = _make_recognizer(tmp_path)
    engine.detect.return_value = [_cand()]
    quality.assess.return_value = _failing_quality("blurry")

    result = r.process_crop(_FAKE_FRAME, tracker_id=1)

    assert result == (None, None, False)
    engine.embed.assert_not_called()
    assert r.list_persons() == []


# ─── Consenso de 3 muestras antes de registrar una persona nueva ─────────────
def TEST_process_crop_needs_consensus_to_register(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    engine.detect.return_value = [_cand()]
    enc = _unit_vec(1)
    engine.embed.return_value = enc

    r1 = r.process_crop(_FAKE_FRAME, tracker_id=1)
    r2 = r.process_crop(_FAKE_FRAME, tracker_id=1)
    r3 = r.process_crop(_FAKE_FRAME, tracker_id=1)

    assert r1 == (None, None, False)
    assert r2 == (None, None, False)
    pid, name, is_new = r3
    assert pid is not None and is_new is True
    persons = r.list_persons()
    assert len(persons) == 1
    assert persons[0]["sample_count"] == 3


# ─── Muestra inconsistente resetea el buffer de consenso ─────────────────────
def TEST_process_crop_inconsistent_sample_resets_buffer(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    engine.detect.return_value = [_cand()]
    base = _unit_vec(2)
    # Cada muestra esta lejos de la anterior (similitud muy por debajo de
    # CONSENSUS_TOLERANCE=0.30) — nunca se acumulan 3 consistentes.
    engine.embed.side_effect = [base, _unit_vec(3), _unit_vec(4)]

    for _ in range(3):
        assert r.process_crop(_FAKE_FRAME, tracker_id=1) == (None, None, False)

    assert r.list_persons() == []


# ─── Match contra persona existente: una sola muestra basta ──────────────────
def TEST_process_crop_matches_existing_person_single_sample(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    enc = _unit_vec(5)
    with r._lock:
        pid = r._register(enc)

    engine.detect.return_value = [_cand()]
    engine.embed.return_value = enc

    rpid, _, is_new = r.process_crop(_FAKE_FRAME, tracker_id=1)
    assert rpid == pid
    assert is_new is False


# ─── Match ambiguo entre dos personas: no decide ni registra ─────────────────
def TEST_ambiguous_match_neither_decides_nor_registers(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    base = _unit_vec(6)
    with r._lock:
        r._register(_at_similarity(base, 0.60, seed=7))
        r._register(_at_similarity(base, 0.55, seed=8))  # gap 0.05 < MATCH_MARGIN=0.10

    engine.detect.return_value = [_cand()]
    engine.embed.return_value = base

    for _ in range(3):
        assert r.process_crop(_FAKE_FRAME, tracker_id=1) == (None, None, False)

    assert len(r.list_persons()) == 2
    assert r.get_cached(1) is None


# ─── Match decisivo con margen suficiente: acepta al primer intento ──────────
def TEST_decisive_match_with_margin_accepts(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    base = _unit_vec(9)
    with r._lock:
        pid_a = r._register(_at_similarity(base, 0.90, seed=10))
        r._register(_at_similarity(base, 0.50, seed=11))  # gap 0.40 >= MATCH_MARGIN

    engine.detect.return_value = [_cand()]
    engine.embed.return_value = base

    rpid, _, is_new = r.process_crop(_FAKE_FRAME, tracker_id=1)
    assert rpid == pid_a
    assert is_new is False


# ─── Dos muestras de la MISMA persona no bloquean el ratio test ──────────────
def TEST_same_person_samples_do_not_block_ratio_test(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    base = _unit_vec(12)
    with r._lock:
        pid_a = r._register(_at_similarity(base, 0.90, seed=13))
        # Segunda muestra de A, muy cercana a la primera (self-similarity alta) —
        # sin agrupar por persona, esta seria el "runner-up" y bloquearia el match.
        r._person_ids.append(pid_a)
        r._person_names.append(None)
        second_a = _at_similarity(base, 0.88, seed=14)
        r._encodings.append(second_a)
        r._index.add(pid_a, second_a)
        r._register(_at_similarity(base, 0.40, seed=15))

    engine.detect.return_value = [_cand()]
    engine.embed.return_value = base

    rpid, _, is_new = r.process_crop(_FAKE_FRAME, tracker_id=1)
    assert rpid == pid_a
    assert is_new is False


# ─── Se elige la cara de la mitad superior del crop ───────────────────────────
def TEST_select_face_prefers_upper_half(tmp_path):
    r, engine, quality = _make_recognizer(tmp_path)
    upper = _cand(bbox=(0, 0, 70, 70))         # centro y=35, mitad superior de 200
    lower = _cand(bbox=(110, 110, 199, 199))   # centro y=154.5, mitad inferior, mas grande
    engine.detect.return_value = [lower, upper]
    engine.embed.return_value = _unit_vec(16)

    r.process_crop(_FAKE_FRAME, tracker_id=1)
    r.process_crop(_FAKE_FRAME, tracker_id=1)
    r.process_crop(_FAKE_FRAME, tracker_id=1)

    # embed() se llama con el FaceCandidate elegido — verificar que es `upper`
    called_cand = engine.embed.call_args_list[0].args[1]
    assert called_cand.bbox == upper.bbox


# ─── Re-verificación: el voto mayoritario corrige una identidad cacheada ─────
def TEST_reverify_majority_vote_corrects_identity(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    base = _unit_vec(17)
    other = _unit_vec(18)
    with r._lock:
        pid_a = r._register(base)
        pid_b = r._register(other)

    engine.detect.return_value = [_cand()]
    engine.embed.return_value = base
    rpid, _, _ = r.process_crop(_FAKE_FRAME, tracker_id=1)
    assert rpid == pid_a

    engine.embed.return_value = other  # a partir de aqui la cara "es" B
    r2, _, _ = r.process_crop(_FAKE_FRAME, tracker_id=1)
    assert r2 == pid_a                      # empate [A,B] -> sin flip
    assert r.get_cached(1) == (pid_a, None)

    r3, _, _ = r.process_crop(_FAKE_FRAME, tracker_id=1)
    assert r3 == pid_b                      # mayoria [A,B,B] -> corrige
    assert r.get_cached(1) == (pid_b, None)


# ─── Cara desconocida durante re-verify no crea persona nueva ────────────────
def TEST_unknown_face_during_reverify_does_not_register(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    base = _unit_vec(19)
    with r._lock:
        pid_a = r._register(base)

    engine.detect.return_value = [_cand()]
    engine.embed.return_value = base
    r.process_crop(_FAKE_FRAME, tracker_id=1)
    assert r.get_cached(1) == (pid_a, None)

    engine.embed.return_value = _unit_vec(20)  # cara desconocida
    for _ in range(3):
        assert r.process_crop(_FAKE_FRAME, tracker_id=1) == (None, None, False)

    assert len(r.list_persons()) == 1
    assert r.get_cached(1) == (pid_a, None)


# ---------------------------------------------------------------------------
# enroll_named_face
# ---------------------------------------------------------------------------

def TEST_enroll_named_face_no_face_returns_none(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    engine.detect.return_value = []
    assert r.enroll_named_face(_FAKE_FRAME, "Bob") is None


def TEST_enroll_named_face_registers_new_person(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    engine.detect.return_value = [_cand()]
    engine.embed.return_value = _unit_vec(21)

    pid = r.enroll_named_face(_FAKE_FRAME, "Carol")
    assert pid is not None and pid > 0
    assert any(p["name"] == "Carol" for p in r.list_persons())


def TEST_enroll_named_face_updates_existing_person(tmp_path):
    r, engine, _ = _make_recognizer(tmp_path)
    enc = _unit_vec(22)
    engine.detect.return_value = [_cand()]
    engine.embed.return_value = enc

    pid1 = r.enroll_named_face(_FAKE_FRAME, "Dave")
    pid2 = r.enroll_named_face(_FAKE_FRAME, "David")  # misma cara

    assert pid1 == pid2
    persons = r.list_persons()
    assert any(p["name"] == "David" for p in persons)
    assert not any(p["name"] == "Dave" for p in persons)


def TEST_enroll_named_face_unavailable_returns_none(tmp_path):
    r, _, _ = _make_recognizer(tmp_path, available=False)
    assert r.enroll_named_face(_FAKE_FRAME, "Eve") is None
