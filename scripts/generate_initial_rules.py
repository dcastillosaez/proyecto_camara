"""Genera config/rules.yaml con las reglas por defecto (DIR-01).

config/rules.yaml solo se lee al arrancar con la tabla `rules` vacia; en cuanto se
crea una regla desde la API, la fuente de verdad es la base de datos. Volver a
ejecutar este script SOBRESCRIBE cualquier edicion manual del fichero.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from backend.config import Settings, get_settings


def build_rules(settings: Settings) -> dict[str, Any]:
    """Reglas por defecto (DIR-01): intrusion y persona desconocida avisan y GRABAN.

    Antes solo avisaban (notify), asi que una instalacion limpia no grababa nunca.
    OBJECT_LEFT no graba por defecto hasta calibrar object_person_radius_px: un radio
    mal ajustado llenaria el disco y la cuota de Drive. Los alert_on_* de v1 se
    retiraron (no hacian nada en tiempo de ejecucion)."""
    debounce = settings.alert_cooldown_secs
    rules: list[dict[str, Any]] = [
        {
            # INTRUSION: cruce fuera del horario de acceso o entrada en zona restricted.
            "name": "intrusion",
            "enabled": True,
            "when": {"event": "INTRUSION"},
            "debounce_secs": debounce,
            "actions": [{"type": "notify"}, {"type": "record"}],
        },
        {
            "name": "persona_desconocida",
            "enabled": True,
            "when": {"event": "UNKNOWN_PERSON"},
            "debounce_secs": debounce,
            "actions": [{"type": "notify"}, {"type": "record"}],
        },
    ]

    if settings.alert_count_threshold > 0:
        rules.append({
            "name": "aglomeracion",
            "enabled": True,
            "when": {"event": "CROWD_DETECTED"},
            "debounce_secs": debounce,
            "actions": [{"type": "notify"}],
        })

    return {"version": 1, "rules": rules}


def main(output_path: str = "config/rules.yaml") -> None:
    settings = get_settings()
    doc = build_rules(settings)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Generado por scripts/generate_initial_rules.py: reglas por defecto (DIR-01).\n"
        "# Intrusion y persona desconocida avisan y graban; OBJECT_LEFT no graba hasta\n"
        "# calibrar object_person_radius_px. Solo se lee con la tabla `rules` vacia.\n"
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
