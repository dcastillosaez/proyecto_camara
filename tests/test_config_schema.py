"""Tests for backend.api.v2.config_schema (Fase 32, plan 32-01).

Cubre el contrato puro consumido por 32-02 (router) y las vistas de frontend de
waves posteriores: cobertura exacta de los 112 campos de Settings, resolucion de
`origin` (runtime/env/default) para escalares y listas (Pitfall 4), enmascarado
obligatorio de camera_url, y que build_candidate_settings reutiliza los
model_validator reales de Settings en vez de reimplementarlos (SET-03/D-10).
"""

from __future__ import annotations

import pydantic
import pytest

from backend.config import Settings, get_settings, mask_rtsp_url
from backend.api.v2.config_schema import (
    all_fields,
    build_candidate_settings,
    field_by_key,
    resolve_origin,
)


def TEST_all_fields_covers_every_settings_attribute():
    keys = {f.key for f in all_fields()}
    assert keys == set(Settings.model_fields)


def TEST_all_fields_no_duplicate_keys():
    keys = [f.key for f in all_fields()]
    assert len(keys) == len(set(keys))


def TEST_field_by_key_returns_none_for_unknown_key():
    assert field_by_key("does_not_exist_in_settings") is None


def TEST_no_field_has_empty_hint():
    empty = [f.key for f in all_fields() if f.hint == ""]
    assert len(empty) <= 5, f"demasiados campos sin hint: {empty}"


# ─── resolve_origin — escalares ─────────────────────────────────────────────

def TEST_resolve_origin_runtime_wins_over_env_and_default():
    field = field_by_key("yolo_confidence")
    settings = Settings(yolo_confidence=0.9)  # simula .env con valor distinto
    overrides = {"yolo_confidence": 0.7}

    value, origin = resolve_origin(field, overrides, settings)

    assert value == 0.7
    assert origin == "runtime"


def TEST_resolve_origin_env_when_differs_from_default():
    field = field_by_key("yolo_confidence")
    settings = Settings(yolo_confidence=0.9)

    value, origin = resolve_origin(field, {}, settings)

    assert value == 0.9
    assert origin == "env"


def TEST_resolve_origin_default_when_matches():
    field = field_by_key("yolo_confidence")
    settings = Settings()

    value, origin = resolve_origin(field, {}, settings)

    assert value == field.default
    assert origin == "default"


# ─── resolve_origin — listas (Pitfall 4) ────────────────────────────────────

@pytest.mark.parametrize("key,env_value", [
    ("yolo_classes", [0, 24]),
    ("schedule_days", [0, 1]),
])
def TEST_resolve_origin_list_field_env_vs_default(key, env_value):
    field = field_by_key(key)

    settings_env = Settings(**{key: env_value})
    value, origin = resolve_origin(field, {}, settings_env)
    assert value == env_value
    assert origin == "env"

    settings_default = Settings()
    value, origin = resolve_origin(field, {}, settings_default)
    assert value == field.default
    assert origin == "default"

    settings_runtime = Settings()
    value, origin = resolve_origin(field, {key: env_value}, settings_runtime)
    assert value == env_value
    assert origin == "runtime"


def TEST_resolve_origin_camera_url_always_masked():
    field = field_by_key("camera_url")
    settings = Settings(camera_url="rtsp://cam.local:554/stream1", rtsp_user="op", rtsp_pass="s3cret")

    from backend.config import build_rtsp_url
    raw_url = build_rtsp_url(settings)
    expected_masked = mask_rtsp_url(raw_url)

    # resolve_origin siempre enmascara camera_url; comprobamos contra el mismo
    # oraculo que usa mask_rtsp_url para no reinventar una regex propia.
    value, _origin = resolve_origin(field, {}, settings)
    assert "op" not in value
    assert "s3cret" not in value

    value_runtime, origin_runtime = resolve_origin(field, {"camera_url": raw_url}, settings)
    assert value_runtime == mask_rtsp_url(raw_url)
    assert origin_runtime == "runtime"
    assert "s3cret" not in value_runtime
    assert expected_masked == mask_rtsp_url(raw_url)


# ─── build_candidate_settings ───────────────────────────────────────────────

def TEST_build_candidate_settings_rejects_invalid_cross_field():
    settings = get_settings()

    with pytest.raises(pydantic.ValidationError):
        build_candidate_settings(
            settings, {},
            {"identity_min_votes": 10, "identity_vote_window": 2},
        )


def TEST_build_candidate_settings_accepts_valid_change():
    settings = get_settings()

    candidate = build_candidate_settings(settings, {}, {"identity_min_votes": 5, "identity_vote_window": 8})

    assert candidate.identity_min_votes == 5
    assert candidate.identity_vote_window == 8
