"""Snapshot de evento (Fase 30 — OPS-07/OPS-08).

El recorte del bbox se escribe SIEMPRE via asyncio.to_thread: _capture_event_snapshot
la llama el pipeline de eventos, que es una corrutina, y un cv2.imwrite sincrono ahi
produce micro-pausas en MJPEG y WS (CLAUDE.md "no ejecutar CPU pesado en el event loop").
"""
from __future__ import annotations

import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

import backend.main as main
from backend.events.types import Event, EventType


# Settings falso en vez de Settings(snapshot_dir=tmp_path): el validador de la
# Task 1 exige que snapshot_dir quede DENTRO del proyecto (T-30-12) y tmp_path
# de pytest vive fuera. Escribir en el arbol del repo durante los tests seria peor.
def _settings(tmp_path: Path, **over):
    base = dict(
        snapshot_enabled=True,
        snapshot_dir=str(tmp_path / "snaps"),
        snapshot_max_width=320,
        snapshot_min_interval_secs=5.0,
        snapshot_retention_days=30,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _fake_manager(frame):
    pipeline = SimpleNamespace(get_frame=lambda: frame)
    return SimpleNamespace(get=lambda camera_id: pipeline)


def _event(**over) -> Event:
    kwargs = dict(
        type=EventType.LINE_CROSSED,
        camera_id="cam1",
        ts=datetime.datetime(2026, 8, 20, 18, 30, 0),
        track_id=7,
        bbox=(10, 20, 110, 140),
    )
    kwargs.update(over)
    return Event(**kwargs)


@pytest.fixture(autouse=True)
def _isolate_throttle(monkeypatch):
    """El throttle es estado de modulo: cada test arranca con la tabla vacia."""
    monkeypatch.setattr(main, "_snapshot_last", {})


# ─── El recorte se escribe en disco ───────────────────────────────────────────
# La ruta devuelta es relativa y el fichero existe con contenido: es lo que la
# linea temporal usa como miniatura y "Marcar como persona" como precarga.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_capture_snapshot_writes_cropped_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path))
    frame = np.zeros((240, 320, 3), np.uint8)
    monkeypatch.setattr(main, "camera_manager", _fake_manager(frame))

    path = await main._capture_event_snapshot(_event())

    assert path is not None
    assert path.endswith(".jpg")
    on_disk = Path(path)
    assert on_disk.is_file()
    assert on_disk.stat().st_size > 0
    assert on_disk.parent.name == "20260820"


async def TEST_capture_snapshot_returns_none_without_bbox(tmp_path, monkeypatch):
    """Sin bbox no hay nada que recortar: ni ruta ni fichero."""
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(main, "camera_manager", _fake_manager(np.zeros((240, 320, 3), np.uint8)))

    assert await main._capture_event_snapshot(_event(bbox=None)) is None
    assert not (tmp_path / "snaps").exists()


async def TEST_capture_snapshot_returns_none_when_disabled(tmp_path, monkeypatch):
    """snapshot_enabled=False es la valvula de escape sin tocar codigo (T-30-13)."""
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path, snapshot_enabled=False))
    monkeypatch.setattr(main, "camera_manager", _fake_manager(np.zeros((240, 320, 3), np.uint8)))

    assert await main._capture_event_snapshot(_event()) is None


# ─── Throttle por track ───────────────────────────────────────────────────────
# Un track que dispara eventos en rafaga no puede escribir un JPEG por evento:
# es la cota de disco de T-30-13 junto con la purga y el reescalado.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_capture_snapshot_throttles_per_track(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(main, "camera_manager", _fake_manager(np.zeros((240, 320, 3), np.uint8)))

    assert await main._capture_event_snapshot(_event(track_id=7)) is not None
    assert await main._capture_event_snapshot(_event(track_id=7)) is None
    assert await main._capture_event_snapshot(_event(track_id=8)) is not None


async def TEST_capture_snapshot_uses_to_thread(tmp_path, monkeypatch):
    """El imwrite pasa por asyncio.to_thread, nunca directo desde la corrutina."""
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(main, "camera_manager", _fake_manager(np.zeros((240, 320, 3), np.uint8)))
    to_thread = AsyncMock(return_value=True)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)

    path = await main._capture_event_snapshot(_event())

    assert path is not None
    to_thread.assert_awaited_once()
    assert to_thread.await_args.args[0] is main.cv2.imwrite


async def TEST_capture_snapshot_clamps_bbox_to_frame(tmp_path, monkeypatch):
    """Un bbox desbordado (o negativo) se recorta al frame en vez de reventar."""
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(main, "camera_manager", _fake_manager(np.zeros((240, 320, 3), np.uint8)))

    path = await main._capture_event_snapshot(_event(bbox=(-20, -20, 9999, 9999)))

    assert path is not None
    assert Path(path).is_file()


# ─── Purga por directorio de dia ──────────────────────────────────────────────
# Los snapshots se agrupan en YYYYMMDD justamente para que la purga sea un
# rmtree por directorio y no un stat por fichero.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_purge_old_snapshots_removes_old_day_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path))
    base = tmp_path / "snaps"
    today = datetime.datetime.now()
    old_dir = base / (today - datetime.timedelta(days=60)).strftime("%Y%m%d")
    new_dir = base / today.strftime("%Y%m%d")
    for d in (old_dir, new_dir):
        d.mkdir(parents=True)
        (d / "a.jpg").write_bytes(b"x")

    removed = await main._purge_old_snapshots(30)

    assert removed == 1
    assert not old_dir.exists()
    assert (new_dir / "a.jpg").is_file()
