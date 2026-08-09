"""FaceQualityAssessor — size/blur/pose gating with an explicit rejection reason.

SPEC_v2.md §5.4 fixes the contract (FaceQuality fields, default thresholds)
but not the pose-estimation method. yaw/pitch/roll here are a simple
geometric approximation from the 5 landmarks insightface already returns
(no separate pose-estimation model): under insightface's own arcface_dst
template, a frontal face has the nose roughly centered between the eyes and
vertically centered between the eye line and mouth line — the further the
nose drifts from that midpoint (relative to the face's own scale), the more
the head has turned. This is intentionally cheap and approximate, not a
metric pose estimate; only yaw actually gates rejection ("extreme_pose"
per the phase's stated success criterion), pitch/roll/brightness are
reported for logging/debugging only.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# insightface's 5-point order: left_eye, right_eye, nose, left_mouth, right_mouth
_LEFT_EYE, _RIGHT_EYE, _NOSE, _LEFT_MOUTH, _RIGHT_MOUTH = range(5)


@dataclass
class FaceQuality:
    size_px: int
    blur: float
    yaw: float
    pitch: float
    roll: float
    brightness: float
    passed: bool
    reason: str | None  # "too_small" | "blurry" | "extreme_pose" | None


class FaceQualityAssessor:
    def __init__(
        self,
        min_size_px: int = 60,
        max_blur: float = 100.0,
        max_yaw_deg: float = 40.0,
    ) -> None:
        self._min_size_px = min_size_px
        self._max_blur = max_blur
        self._max_yaw_deg = max_yaw_deg

    def assess(self, crop: np.ndarray, kps: np.ndarray) -> FaceQuality:
        h, w = crop.shape[:2]
        size_px = min(h, w)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        yaw, pitch, roll = self._estimate_pose(kps)

        if size_px < self._min_size_px:
            reason = "too_small"
        elif blur < self._max_blur:
            reason = "blurry"
        elif abs(yaw) > self._max_yaw_deg:
            reason = "extreme_pose"
        else:
            reason = None

        return FaceQuality(
            size_px=size_px, blur=blur, yaw=yaw, pitch=pitch, roll=roll,
            brightness=brightness, passed=reason is None, reason=reason,
        )

    @staticmethod
    def _estimate_pose(kps: np.ndarray) -> tuple[float, float, float]:
        left_eye, right_eye = kps[_LEFT_EYE], kps[_RIGHT_EYE]
        nose = kps[_NOSE]
        mouth_center = (kps[_LEFT_MOUTH] + kps[_RIGHT_MOUTH]) / 2
        eye_center = (left_eye + right_eye) / 2
        eye_dist = float(np.linalg.norm(right_eye - left_eye)) or 1.0

        # Yaw: horizontal drift of the nose from the eye midpoint, scaled by
        # half the interocular distance (0 = centered, ~1 = at one eye).
        yaw_ratio = (nose[0] - eye_center[0]) / (eye_dist / 2)
        yaw = float(np.clip(yaw_ratio, -1.5, 1.5)) * 60.0

        # Pitch: vertical drift of the nose from the eye-to-mouth midpoint.
        face_height = float(mouth_center[1] - eye_center[1]) or 1.0
        expected_nose_y = eye_center[1] + face_height / 2
        pitch_ratio = (nose[1] - expected_nose_y) / (face_height / 2)
        pitch = float(np.clip(pitch_ratio, -1.5, 1.5)) * 60.0

        # Roll: tilt of the eye line from horizontal.
        roll = float(np.degrees(np.arctan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0])))

        return yaw, pitch, roll
