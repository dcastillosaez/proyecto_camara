"""One-shot: translate the legacy .env alert_* settings into config/rules.yaml.

Run once when upgrading from v1 (Notifier decided everything). Re-run any time
after changing ALERT_* variables in .env to regenerate the file — it always
overwrites config/rules.yaml, so hand edits made after the first run are lost
on re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from backend.config import Settings, get_settings


def build_rules(settings: Settings) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []

    if settings.alert_on_intrusion:
        rules.append({
            "name": "intrusion",
            "enabled": True,
            "when": {"event": "LINE_CROSSED", "payload": {"is_intrusion": True}},
            "debounce_secs": settings.alert_cooldown_secs,
            "actions": [{"type": "notify"}],
        })

    if settings.alert_on_unknown:
        rules.append({
            "name": "persona_desconocida",
            "enabled": True,
            "when": {"event": "LINE_CROSSED", "person": "unknown"},
            "debounce_secs": settings.alert_cooldown_secs,
            "actions": [{"type": "notify"}],
        })

    if settings.alert_on_detection:
        rules.append({
            "name": "deteccion_persona",
            "enabled": True,
            "when": {"event": "LINE_CROSSED"},
            "debounce_secs": settings.alert_cooldown_secs,
            "actions": [{"type": "notify"}],
        })

    if settings.alert_count_threshold > 0:
        rules.append({
            "name": "aglomeracion",
            "enabled": True,
            "when": {"event": "CROWD_DETECTED"},
            "debounce_secs": settings.alert_cooldown_secs,
            "actions": [{"type": "notify"}],
        })

    return {"version": 1, "rules": rules}


def main(output_path: str = "config/rules.yaml") -> None:
    settings = get_settings()
    doc = build_rules(settings)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Generado por scripts/generate_initial_rules.py a partir de las variables\n"
        "# ALERT_* de .env — reproduce el comportamiento de alertas de v1.\n"
        "#\n"
        "# Este fichero es editable a mano: anade, desactiva o ajusta reglas libremente.\n"
        "# Volver a ejecutar el script SOBRESCRIBE cualquier edicion manual.\n"
        "#\n"
        "# Referencia de esquema (propuesta_mejora/SPEC_v2.md SS6.4):\n"
        "#   when: event, zone, camera, time_range (\"HH:MM-HH:MM\", puede cruzar\n"
        "#         medianoche), days ([0..6], 0=lunes), min_confidence, duration_gte,\n"
        "#         person (\"unknown\" o nombre), payload (match exacto de claves)\n"
        "#   debounce_secs: por (regla, camera_id, person_id|track_id)\n"
        "#   actions: record, snapshot, notify, telegram, webhook, log, upload_drive, set_flag\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    print(f"Generadas {len(doc['rules'])} reglas en {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "config/rules.yaml")
