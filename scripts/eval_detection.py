"""Banco de evaluación de detección y tracking (DET-03).

Reproduce clips anotados a mano con el mismo detector y tracker que el pipeline
(PersonDetector + PersonTracker) y mide lo que importa para el conteo:

- error de conteo: cruces de línea detectados frente a los anotados, por sentido;
- cambios de id: veces que una persona anotada pasa a otro tracker_id;
- tracks falsos por hora: tracks que nunca coinciden con una persona anotada;
- vida mediana de los tracks, para ver la fragmentación.

Sirve para decidir con datos si un ajuste (DET-04 a DET-07, imgsz, modelo, GPU)
mejora o empeora el conteo. No incluye clips: hay que grabarlos y anotarlos
(10-15, con día, noche e infrarrojos). Cada clip lleva un JSON de anotación:

    {
      "video": "clip_dia_01.mp4",          # relativo al JSON
      "line": {"start": [0.0, 0.5], "end": [1.0, 0.5]},   # fracciones del frame
      "expected": {"in": 3, "out": 2},
      "persons": [                          # opcional: cajas por frame
        {"id": "a", "boxes": {"12": [x1, y1, x2, y2], "13": [...]}}
      ]
    }

Sin "persons" solo se calcula el error de conteo.

Uso:
    .venv/Scripts/python.exe scripts/eval_detection.py anotaciones/ --conf 0.45 \
        --imgsz 640 --fps 8 --out resultado.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

IOU_MATCH = 0.5


@dataclass
class ClipAnnotation:
    path: Path
    video: Path
    line: dict[str, list[float]]
    expected_in: int
    expected_out: int
    persons: dict[str, dict[int, list[float]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ClipAnnotation":
        raw = json.loads(path.read_text(encoding="utf-8"))
        persons = {
            str(p["id"]): {int(k): list(map(float, v)) for k, v in p.get("boxes", {}).items()}
            for p in raw.get("persons", [])
        }
        return cls(
            path=path,
            video=(path.parent / raw["video"]).resolve(),
            line=raw["line"],
            expected_in=int(raw["expected"]["in"]),
            expected_out=int(raw["expected"]["out"]),
            persons=persons,
        )


@dataclass
class ClipResult:
    clip: str
    frames: int
    seconds: float
    counted_in: int
    counted_out: int
    expected_in: int
    expected_out: int
    count_error: int
    id_switches: int | None
    false_tracks: int | None
    false_tracks_per_hour: float | None
    tracks: int
    median_track_life_s: float | None


# ─── métricas puras (sin vídeo ni modelo; las prueban los tests) ──────────────
def iou(a: Iterable[float], b: Iterable[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def match_frame(
    gt: dict[str, list[float]], pred: dict[int, list[float]], threshold: float = IOU_MATCH,
) -> dict[str, int]:
    """Empareja personas anotadas con tracks por IoU, de mayor a menor (voraz)."""
    pairs = sorted(
        ((iou(g, p), gid, pid) for gid, g in gt.items() for pid, p in pred.items()),
        reverse=True,
    )
    used_gt: set[str] = set()
    used_pred: set[int] = set()
    matches: dict[str, int] = {}
    for score, gid, pid in pairs:
        if score < threshold:
            break
        if gid in used_gt or pid in used_pred:
            continue
        matches[gid] = pid
        used_gt.add(gid)
        used_pred.add(pid)
    return matches


def id_metrics(
    persons: dict[str, dict[int, list[float]]], predicted: dict[int, dict[int, list[float]]],
) -> tuple[int, int]:
    """(cambios de id, tracks falsos). *predicted* es {frame: {track_id: caja}}.

    Un cambio de id es cada vez que una persona anotada aparece emparejada con un
    tracker_id distinto del último que tuvo. Un track falso es un tracker_id que no
    coincide con ninguna persona anotada en ningún frame."""
    last_id: dict[str, int] = {}
    switches = 0
    matched_tracks: set[int] = set()
    all_tracks: set[int] = set()
    frames = sorted(set(predicted) | {f for boxes in persons.values() for f in boxes})
    for frame in frames:
        pred = predicted.get(frame, {})
        all_tracks.update(pred)
        gt = {gid: boxes[frame] for gid, boxes in persons.items() if frame in boxes}
        for gid, pid in match_frame(gt, pred).items():
            matched_tracks.add(pid)
            if gid in last_id and last_id[gid] != pid:
                switches += 1
            last_id[gid] = pid
    return switches, len(all_tracks - matched_tracks)


def track_lives(predicted: dict[int, dict[int, list[float]]], fps: float) -> list[float]:
    """Segundos entre el primer y el último frame de cada track."""
    first: dict[int, int] = {}
    last: dict[int, int] = {}
    for frame in sorted(predicted):
        for tid in predicted[frame]:
            first.setdefault(tid, frame)
            last[tid] = frame
    return [(last[t] - first[t] + 1) / fps for t in first]


def summarize(results: list[ClipResult]) -> dict[str, Any]:
    hours = sum(r.seconds for r in results) / 3600.0
    with_ids = [r for r in results if r.id_switches is not None]
    false_tracks = sum(r.false_tracks or 0 for r in with_ids)
    return {
        "clips": len(results),
        "count_error_total": sum(r.count_error for r in results),
        "expected_crossings": sum(r.expected_in + r.expected_out for r in results),
        "id_switches_total": sum(r.id_switches or 0 for r in with_ids) if with_ids else None,
        "false_tracks_per_hour": (
            false_tracks / (sum(r.seconds for r in with_ids) / 3600.0)
            if with_ids and any(r.seconds for r in with_ids) else None
        ),
        "hours": round(hours, 4),
    }


# ─── reproducción de un clip ──────────────────────────────────────────────────
FrameSource = Callable[[ClipAnnotation], Iterable[tuple[int, np.ndarray]]]


def video_frames(clip: ClipAnnotation, fps: float) -> Iterable[tuple[int, np.ndarray]]:
    """Frames del vídeo submuestreados a *fps* (como AdaptiveRate), con su índice original."""
    import cv2

    cap = cv2.VideoCapture(str(clip.video))
    if not cap.isOpened():
        raise FileNotFoundError(f"No se puede abrir {clip.video}")
    source_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    step = max(1.0, source_fps / fps)
    next_take = 0.0
    index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if index >= next_take:
                next_take += step
                yield index, frame
            index += 1
    finally:
        cap.release()


def evaluate_clip(
    clip: ClipAnnotation,
    detect: Callable[[np.ndarray], Any],
    tracker_factory: Callable[[list[dict]], Any],
    frames: Iterable[tuple[int, np.ndarray]],
    fps: float,
) -> ClipResult:
    """Pasa cada frame por *detect* y por un tracker nuevo con la línea del clip."""
    import supervision as sv

    tracker = None
    predicted: dict[int, dict[int, list[float]]] = {}
    counted = {"in": 0, "out": 0}
    n = 0
    for index, image in frames:
        n += 1
        if tracker is None:
            h, w = image.shape[:2]
            start, end = clip.line["start"], clip.line["end"]
            tracker = tracker_factory([{
                "id": "eval", "name": "eval",
                "start": sv.Point(int(start[0] * w), int(start[1] * h)),
                "end": sv.Point(int(end[0] * w), int(end[1] * h)),
            }])
        tracked, crossings = tracker.update(detect(image))
        for c in crossings:
            counted[c["direction"]] += 1
        if tracked.tracker_id is not None:
            predicted[index] = {
                int(tid): [float(v) for v in box]
                for tid, box in zip(tracked.tracker_id, tracked.xyxy)
            }
    seconds = n / fps
    switches = false_tracks = per_hour = None
    if clip.persons:
        switches, false_tracks = id_metrics(clip.persons, predicted)
        per_hour = false_tracks / (seconds / 3600.0) if seconds else None
    lives = track_lives(predicted, fps)
    return ClipResult(
        clip=clip.path.name, frames=n, seconds=round(seconds, 2),
        counted_in=counted["in"], counted_out=counted["out"],
        expected_in=clip.expected_in, expected_out=clip.expected_out,
        count_error=abs(counted["in"] - clip.expected_in) + abs(counted["out"] - clip.expected_out),
        id_switches=switches, false_tracks=false_tracks,
        false_tracks_per_hour=round(per_hour, 2) if per_hour is not None else None,
        tracks=len(lives),
        median_track_life_s=round(statistics.median(lives), 2) if lives else None,
    )


def find_annotations(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for p in map(Path, paths):
        found.extend(sorted(p.glob("*.json")) if p.is_dir() else [p])
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("annotations", nargs="+", help="JSON de anotación o directorios con ellos")
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--conf", type=float, default=0.45)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--fps", type=float, default=8.0, help="FPS de proceso (como detection_target_fps)")
    parser.add_argument("--threads", type=int, default=3, help="inference_threads (0 = no tocar)")
    parser.add_argument("--out", help="escribe el resultado completo en este JSON")
    args = parser.parse_args(argv)

    files = find_annotations(args.annotations)
    if not files:
        print("No hay anotaciones que evaluar.", file=sys.stderr)
        return 2

    from backend.detector import PersonDetector
    from backend.tracker import PersonTracker

    detector = PersonDetector(model_path=args.model, confidence=args.conf, imgsz=args.imgsz,
                              inference_threads=args.threads)
    results = []
    for path in files:
        clip = ClipAnnotation.load(path)
        result = evaluate_clip(
            clip, detector.detect_sv,
            lambda lines: PersonTracker(lines=lines, frame_rate=int(round(args.fps))),
            video_frames(clip, args.fps), args.fps,
        )
        results.append(result)
        print(f"{result.clip}: conteo {result.counted_in}/{result.counted_out} "
              f"(esperado {result.expected_in}/{result.expected_out}), "
              f"cambios de id {result.id_switches}, tracks falsos/h {result.false_tracks_per_hour}")
    summary = summarize(results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"params": vars(args), "summary": summary, "clips": [asdict(r) for r in results]},
            ensure_ascii=False, indent=2, default=str,
        ), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
