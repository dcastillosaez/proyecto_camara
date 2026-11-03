"""DET-03: banco de evaluación probado con datos sintéticos (no hay clips reales)."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
import supervision as sv

from backend.tracker import PersonTracker
from scripts import eval_detection as ev


def TEST_iou():
    assert ev.iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert ev.iou([0, 0, 10, 10], [5, 0, 15, 10]) == pytest.approx(50 / 150)
    assert ev.iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def TEST_match_frame_is_one_to_one_and_respects_threshold():
    gt = {"a": [0, 0, 10, 10], "b": [100, 100, 110, 110]}
    pred = {1: [0, 0, 10, 10], 2: [1, 1, 11, 11], 3: [300, 300, 310, 310]}
    assert ev.match_frame(gt, pred) == {"a": 1}


def TEST_id_switch_and_false_track_are_counted():
    persons = {"a": {f: [10 + f, 10, 50 + f, 90] for f in range(10)}}
    predicted = {f: {(1 if f < 5 else 2): [10 + f, 10, 50 + f, 90]} for f in range(10)}
    predicted[3][9] = [400, 400, 440, 480]          # caja sin persona: track falso
    switches, false_tracks = ev.id_metrics(persons, predicted)
    assert switches == 1
    assert false_tracks == 1


def TEST_stable_track_has_no_switches():
    persons = {"a": {f: [10, 10, 50, 90] for f in range(20)}}
    predicted = {f: {7: [11, 10, 51, 90]} for f in range(20) if f != 8}   # un hueco
    assert ev.id_metrics(persons, predicted) == (0, 0)


def TEST_track_lives():
    predicted = {0: {1: [0, 0, 1, 1]}, 1: {1: [0, 0, 1, 1]}, 3: {1: [0, 0, 1, 1], 2: [0, 0, 1, 1]}}
    assert sorted(ev.track_lives(predicted, fps=2.0)) == [0.5, 2.0]


def _walker_boxes(frames: int, w: int = 320, h: int = 240) -> dict[int, list[float]]:
    """Una persona que baja por el centro y cruza la línea horizontal y=0.5."""
    boxes = {}
    for f in range(frames):
        y2 = 40 + f * (h - 40) / (frames - 1)
        boxes[f] = [140.0, y2 - 60, 180.0, y2]
    return boxes


def _fake_detect_from(boxes_by_frame, drop=()):
    state = {"frame": -1}

    def detect(_image):
        state["frame"] += 1
        box = boxes_by_frame.get(state["frame"])
        if box is None or state["frame"] in drop:
            return sv.Detections.empty()
        return sv.Detections(xyxy=np.array([box], dtype=np.float32),
                             confidence=np.array([0.9], dtype=np.float32),
                             class_id=np.array([0]))
    return detect


def _clip(tmp_path, expected_in, expected_out, persons=None):
    return ev.ClipAnnotation(
        path=tmp_path / "sintetico.json", video=tmp_path / "x.mp4",
        line={"start": [0.0, 0.5], "end": [1.0, 0.5]},
        expected_in=expected_in, expected_out=expected_out, persons=persons or {},
    )


def _frames(n, w=320, h=240):
    return ((i, np.zeros((h, w, 3), dtype=np.uint8)) for i in range(n))


def _direction_of_downward_walk(tmp_path) -> tuple[int, int]:
    boxes = _walker_boxes(30)
    r = ev.evaluate_clip(_clip(tmp_path, 0, 0), _fake_detect_from(boxes),
                         lambda lines: PersonTracker(lines=lines, frame_rate=8), _frames(30), fps=8.0)
    return r.counted_in, r.counted_out


def TEST_evaluate_clip_counts_a_synthetic_crossing(tmp_path):
    counted = _direction_of_downward_walk(tmp_path)
    assert sum(counted) == 1                     # una persona, un cruce
    boxes = _walker_boxes(30)
    clip = _clip(tmp_path, *counted, persons={"a": boxes})
    r = ev.evaluate_clip(clip, _fake_detect_from(boxes),
                         lambda lines: PersonTracker(lines=lines, frame_rate=8), _frames(30), fps=8.0)
    assert r.count_error == 0
    assert r.id_switches == 0
    assert r.false_tracks == 0
    assert r.tracks == 1


def TEST_evaluate_clip_reports_count_error(tmp_path):
    clip = _clip(tmp_path, expected_in=2, expected_out=2)
    r = ev.evaluate_clip(clip, _fake_detect_from({}), lambda lines: PersonTracker(lines=lines),
                         _frames(10), fps=8.0)
    assert r.counted_in == r.counted_out == 0
    assert r.count_error == 4
    assert r.id_switches is None          # sin cajas anotadas no se calcula


def TEST_summarize():
    a = ev.ClipResult("a", 80, 10.0, 1, 0, 1, 0, 0, 1, 2, 720.0, 3, 2.0)
    b = ev.ClipResult("b", 80, 10.0, 0, 0, 1, 1, 2, None, None, None, 0, None)
    s = ev.summarize([a, b])
    assert s["clips"] == 2
    assert s["count_error_total"] == 2
    assert s["expected_crossings"] == 3
    assert s["id_switches_total"] == 1
    assert s["false_tracks_per_hour"] == pytest.approx(720.0)


def TEST_annotation_roundtrip_and_cli_on_a_synthetic_video(tmp_path):
    """Extremo a extremo: vídeo sintético vacío + modelo real -> 0 cruces, error 0."""
    video = tmp_path / "vacio.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 8.0, (320, 240))
    assert writer.isOpened()
    for _ in range(16):
        writer.write(np.full((240, 320, 3), 40, dtype=np.uint8))
    writer.release()
    ann = tmp_path / "vacio.json"
    ann.write_text(json.dumps({
        "video": "vacio.avi", "line": {"start": [0, 0.5], "end": [1, 0.5]},
        "expected": {"in": 0, "out": 0},
        "persons": [],
    }), encoding="utf-8")
    loaded = ev.ClipAnnotation.load(ann)
    assert loaded.video == video.resolve() and loaded.persons == {}

    out = tmp_path / "res.json"
    assert ev.main([str(tmp_path), "--fps", "8", "--imgsz", "320", "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["summary"]["count_error_total"] == 0
    assert result["clips"][0]["frames"] == 16


def TEST_cli_without_annotations_fails_cleanly(tmp_path):
    assert ev.main([str(tmp_path)]) == 2
