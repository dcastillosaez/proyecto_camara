"""Soak test sampler — polls /api/v2/metrics (+ local RSS/CPU) to a CSV (Fase 22).

Long-running operational baseline for the resistance test that closes bloque A
(22-CONTEXT.md): run for 8h against the real camera, then compare hour 2 vs
hour 8 for RSS drift and check no queue depth trends upward. A short run
(e.g. --duration 600 --interval 10) is the CI-proportional version.

Usage:
    .venv/Scripts/python.exe scripts/soak_test.py --url https://192.168.1.10:8000 \
        --pid 12345 --duration 28800 --interval 60 --out soak.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Any

import httpx

try:
    import psutil
except ImportError:
    psutil = None

CSV_FIELDS = [
    "timestamp", "elapsed_s", "rss_mb", "cpu_percent",
    "capture_fps", "detection_fps", "face_fps",
    "frames_dropped_total", "active_tracks", "prebuffer_bytes",
    "queue_depth_event_bus", "recording_queue_depth", "upload_queue_depth",
    "e2e_latency_p50", "e2e_latency_p95", "database_size_bytes",
]


def _sum_labeled(section: dict[str, Any], key: str) -> float:
    """Sum a gauge/counter across all label combinations (e.g. per-camera)."""
    values = section.get(key, {})
    return sum(v for v in values.values() if isinstance(v, (int, float)))


def _first_labeled(section: dict[str, Any], key: str) -> float:
    """First value of a labeled gauge — used where a single camera is expected."""
    values = section.get(key, {})
    for v in values.values():
        if isinstance(v, (int, float)):
            return v
    return 0.0


def sample_once(client: httpx.Client, base_url: str, proc: "psutil.Process | None") -> dict[str, Any]:
    resp = client.get(f"{base_url}/api/v2/metrics", timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    gauges = data.get("gauges", {})
    counters = data.get("counters", {})
    e2e = data.get("e2e_percentiles", {})

    row = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": 0,  # filled by the caller
        "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1) if proc else "",
        "cpu_percent": proc.cpu_percent(interval=None) if proc else "",
        "capture_fps": _first_labeled(gauges, "capture_fps"),
        "detection_fps": _first_labeled(gauges, "detection_fps"),
        "face_fps": _first_labeled(gauges, "face_fps"),
        "frames_dropped_total": _sum_labeled(counters, "frames_dropped_total"),
        "active_tracks": _first_labeled(gauges, "active_tracks"),
        "prebuffer_bytes": _first_labeled(gauges, "prebuffer_bytes"),
        "queue_depth_event_bus": _first_labeled(gauges, "queue_depth"),
        "recording_queue_depth": _first_labeled(gauges, "recording_queue_depth"),
        "upload_queue_depth": _first_labeled(gauges, "upload_queue_depth"),
        "e2e_latency_p50": e2e.get("p50", ""),
        "e2e_latency_p95": e2e.get("p95", ""),
        "database_size_bytes": _first_labeled(gauges, "database_size_bytes"),
    }
    return row


def run(
    base_url: str, out_path: str, duration: float, interval: float,
    pid: int | None, user: str | None, password: str | None,
) -> None:
    proc = None
    if pid is not None:
        if psutil is None:
            print("psutil not installed — RSS/CPU columns will be empty", file=sys.stderr)
        else:
            proc = psutil.Process(pid)
            proc.cpu_percent(interval=None)  # first call primes the internal counter

    auth = (user, password) if user else None
    out_file = Path(out_path)
    is_new = not out_file.exists()

    start = time.monotonic()
    with httpx.Client(auth=auth, verify=False) as client, out_file.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()

        while True:
            elapsed = time.monotonic() - start
            try:
                row = sample_once(client, base_url, proc)
                row["elapsed_s"] = round(elapsed, 1)
                writer.writerow(row)
                f.flush()
                print(f"[{row['timestamp']}] elapsed={elapsed:.0f}s "
                      f"rss={row['rss_mb']}MB cpu={row['cpu_percent']}% "
                      f"capture={row['capture_fps']} detect={row['detection_fps']} "
                      f"dropped={row['frames_dropped_total']} "
                      f"e2e_p95={row['e2e_latency_p95']}")
            except Exception as exc:
                print(f"sample failed: {exc}", file=sys.stderr)

            if elapsed >= duration:
                break
            time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of the running server")
    parser.add_argument("--out", default="soak.csv", help="CSV output path (appended if it exists)")
    parser.add_argument("--duration", type=float, default=8 * 3600, help="Total seconds to run (default: 8h)")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between samples")
    parser.add_argument("--pid", type=int, default=None, help="Server process PID, for RSS/CPU sampling")
    parser.add_argument("--user", default=None, help="Dashboard Basic Auth user, if enabled")
    parser.add_argument("--password", default=None, help="Dashboard Basic Auth password, if enabled")
    args = parser.parse_args()

    run(args.url, args.out, args.duration, args.interval, args.pid, args.user, args.password)
