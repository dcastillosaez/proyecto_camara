"""Unit tests for backend.stream.RTSPStream (drain thread + reconnection)."""

import time
from unittest.mock import MagicMock, call, patch

import numpy as np

from backend.stream import RTSPStream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(value: int) -> np.ndarray:
    """Create a 720p frame filled with *value* (0-255)."""
    frame = np.empty((720, 1280, 3), dtype=np.uint8)
    frame.fill(value)
    return frame


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_drain_keeps_latest_frame(mock_video_capture):
    """After draining 5 distinct frames, get_frame() returns the last one."""
    frames = [_make_frame(i) for i in range(5)]
    call_count = {"n": 0}

    def _read_side_effect():
        idx = min(call_count["n"], len(frames) - 1)
        call_count["n"] += 1
        return (True, frames[idx].copy())

    cap = mock_video_capture._mock_cap
    cap.read.side_effect = _read_side_effect

    stream = RTSPStream("rtsp://fake")
    stream.start()
    time.sleep(0.3)
    stream.stop()

    result = stream.get_frame()
    assert result is not None
    # The last frame value should be 4
    assert result[0, 0, 0] == 4


def test_get_frame_returns_copy():
    """The ndarray returned by get_frame() is a copy, not the internal ref."""
    stream = RTSPStream("rtsp://fake")
    stream._frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    frame = stream.get_frame()
    assert frame is not stream._frame
    # Mutating the copy must not affect the internal frame
    frame[0, 0, 0] = 255
    assert stream._frame[0, 0, 0] == 0


@patch("backend.stream.time.sleep")
def test_reconnect_on_failure(mock_sleep, mock_video_capture):
    """On read() failure, RTSPStream releases and creates a new VideoCapture."""
    good_frame = _make_frame(42)
    cap = mock_video_capture._mock_cap

    # Fail twice, then succeed
    cap.read.side_effect = [
        (False, None),
        (False, None),
        (True, good_frame.copy()),
    ] + [(True, good_frame.copy())] * 200

    stream = RTSPStream("rtsp://fake")
    stream.start()
    time.sleep(0.3)
    stream.stop()

    # VideoCapture should have been instantiated more than once (reconnection)
    assert mock_video_capture.call_count >= 2


@patch("backend.stream.time.sleep")
def test_backoff_increases(mock_sleep, mock_video_capture):
    """Reconnection delays grow exponentially: 1, 2, 4, 8, 16."""
    cap = mock_video_capture._mock_cap

    # Fail 5 reconnection attempts, then succeed
    fail_cap = MagicMock()
    fail_cap.isOpened.return_value = False

    success_cap = MagicMock()
    success_cap.isOpened.return_value = True
    success_cap.read.return_value = (True, _make_frame(1))

    # First call (initial), then 5 failures, then success
    caps = [cap] + [fail_cap] * 5 + [success_cap] + [success_cap] * 50
    mock_video_capture.side_effect = caps

    # Initial cap.read fails to trigger reconnect
    cap.read.return_value = (False, None)

    stream = RTSPStream("rtsp://fake")
    stream.start()
    time.sleep(0.5)
    stream.stop()

    # Extract sleep delays from reconnection
    sleep_args = [c.args[0] for c in mock_sleep.call_args_list if c.args]
    # Should see exponential growth: 1, 2, 4, 8, 16
    expected = [1.0, 2.0, 4.0, 8.0, 16.0]
    assert len(sleep_args) >= 5
    for i, exp in enumerate(expected):
        assert sleep_args[i] == exp, f"Delay {i}: expected {exp}, got {sleep_args[i]}"


def test_stop_releases_capture(mock_video_capture):
    """After stop(), VideoCapture.release() is called."""
    cap = mock_video_capture._mock_cap
    good_frame = _make_frame(1)
    cap.read.return_value = (True, good_frame)

    stream = RTSPStream("rtsp://fake")
    stream.start()
    time.sleep(0.1)
    stream.stop()
    time.sleep(0.1)

    cap.release.assert_called()


def test_get_frame_none_before_start():
    """Before any frame arrives, get_frame() returns None."""
    stream = RTSPStream("rtsp://fake")
    assert stream.get_frame() is None
