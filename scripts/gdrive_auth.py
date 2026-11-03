"""Autoriza la subida a Google Drive (DIR-03).

El backend ya no abre el navegador desde el hilo de subida: si el token falta o
caduca, la cola se pausa y espera. Este script hace el flujo OAuth a mano, en el
equipo del servidor, y deja el token en GDRIVE_TOKEN_PATH (data/token.json por
defecto). La cola lo detecta al cambiar el fichero y reanuda sola.

Uso:
    .venv/Scripts/python.exe scripts/gdrive_auth.py
"""

from __future__ import annotations

import sys

from backend.config import get_settings
from backend.gdrive import load_credentials


def main() -> int:
    s = get_settings()
    load_credentials(s.gdrive_credentials_path, s.gdrive_token_path, interactive=True)
    print(f"Drive autorizado. Token guardado en {s.gdrive_token_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
