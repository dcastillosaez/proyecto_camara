"""Tests for backend.perception.face.quality.FaceQualityAssessor — synthetic images.

The three gates (size, blur, pose) operate purely on image/geometry metrics,
not face semantics, so synthetic crops (noise, gradients, blurred patches)
and hand-built landmark arrays exercise them without needing a real face.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.perception.face.quality import FaceQualityAssessor

# Frontal 5-point layout matching insightface's arcface_dst template
# (left_eye, right_eye, nose, left_mouth, right_mouth), scaled to a 200x200 crop.
_FRONTAL_KPS = np.array(
    [[68, 92], [131, 92], [100, 128], [74, 165], [126, 165]], dtype=np.float32
)
# Nose pushed hard toward the right eye — simulates a strong yaw turn.
_YAW_KPS = np.array(
    [[68, 92], [131, 92], [122, 128], [74, 165], [126, 165]], dtype=np.float32
)


def _sharp_crop(size: int = 200) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, (size, size, 3), dtype=np.uint8)


def _blurry_crop(size: int = 200) -> np.ndarray:
    sharp = _sharp_crop(size)
    return cv2.GaussianBlur(sharp, (31, 31), sigmaX=15)


@pytest.fixture
def assessor() -> FaceQualityAssessor:
    return FaceQualityAssessor(min_size_px=60, max_blur=100.0, max_yaw_deg=40.0)


def TEST_rejects_small_face(assessor):
    tiny = _sharp_crop(40)
    quality = assessor.assess(tiny, _FRONTAL_KPS * (40 / 200))
    assert quality.passed is False
    assert quality.reason == "too_small"


def TEST_rejects_blurry_face(assessor):
    blurry = _blurry_crop(200)
    quality = assessor.assess(blurry, _FRONTAL_KPS)
    assert quality.passed is False
    assert quality.reason == "blurry"


def TEST_rejects_extreme_pose(assessor):
    sharp = _sharp_crop(200)
    quality = assessor.assess(sharp, _YAW_KPS)
    assert quality.passed is False
    assert quality.reason == "extreme_pose"


def TEST_accepts_good_face(assessor):
    sharp = _sharp_crop(200)
    quality = assessor.assess(sharp, _FRONTAL_KPS)
    assert quality.passed is True
    assert quality.reason is None


def TEST_quality_reports_all_metrics(assessor):
    tiny_blurry = _blurry_crop(40)
    quality = assessor.assess(tiny_blurry, _FRONTAL_KPS * (40 / 200))
    assert quality.size_px > 0
    assert quality.blur >= 0.0
    assert isinstance(quality.yaw, float)
    assert isinstance(quality.pitch, float)
    assert isinstance(quality.roll, float)
    assert quality.brightness >= 0.0
