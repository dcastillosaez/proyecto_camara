"""Shared fixtures for the test suite."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture
def fake_frame():
    """Return a synthetic 720p BGR frame (all zeros)."""
    return np.zeros((720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def mock_video_capture(fake_frame):
    """Patch cv2.VideoCapture with a configurable MagicMock.

    By default the mock returns ``isOpened()=True`` and
    ``read()=(True, fake_frame)`` on every call.
    """
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, fake_frame.copy())

    with patch("backend.pipeline.capture.cv2.VideoCapture", return_value=mock_cap) as factory:
        factory._mock_cap = mock_cap  # expose for tests
        yield factory
