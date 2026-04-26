"""Phase 12 — Alert and notification dispatcher.

Fires alerts on three channels (webhook, Telegram) for four event types:
  - intrusion   : crossing inside off-schedule hours (is_intrusion=True)
  - unknown     : crossing by unrecognised person
  - threshold   : daily count reaches alert_count_threshold
  - camera      : RTSP feed lost / recovered

Each alert type has an independent cooldown so a busy scene doesn't spam.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


@dataclass
class Notifier:
    webhook_url: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    alert_on_intrusion: bool = True
    alert_on_unknown: bool = True
    alert_on_detection: bool = False
    cooldown_secs: float = 60.0
    count_threshold: int = 0

    _last_fire: dict[str, datetime.datetime] = field(default_factory=dict, init=False, repr=False)

    # ------------------------------------------------------------------
    # Public — called from main.py
    # ------------------------------------------------------------------

    async def fire_event(self, event: dict) -> None:
        """Evaluate a crossing event and dispatch alerts if warranted."""
        is_intrusion = bool(event.get("is_intrusion", False))
        person_name = event.get("person_name")
        is_unknown = not person_name

        if is_intrusion and self.alert_on_intrusion:
            key, title = "intrusion", "⚠️ INTRUSIÓN DETECTADA"
        elif is_unknown and self.alert_on_unknown:
            key, title = "unknown", "👤 Persona desconocida detectada"
        elif self.alert_on_detection:
            key, title = "detection", "🚶 Persona detectada"
        else:
            return

        if not self._can_fire(key):
            return
        self._mark(key)

        direction = event.get("direction", "?")
        ts = _ts(event.get("timestamp"))
        text = f"{title}\nDirección: {direction}\n{ts}"
        payload = {
            "type": key,
            "title": title,
            "direction": direction,
            "timestamp": ts,
            "person_name": person_name,
            "is_intrusion": is_intrusion,
        }
        await self._send(text, payload)

    async def fire_count_threshold(self, count: int) -> None:
        """Fire when daily count crosses the configured threshold."""
        if self.count_threshold <= 0 or count < self.count_threshold:
            return
        if not self._can_fire("threshold"):
            return
        self._mark("threshold")
        text = f"📊 Umbral alcanzado: {count} personas hoy"
        await self._send(text, {"type": "threshold", "count": count, "timestamp": _ts()})

    async def fire_camera_offline(self) -> None:
        if not self._can_fire("offline"):
            return
        self._mark("offline")
        await self._send(
            "🔴 Cámara desconectada — sin señal RTSP",
            {"type": "camera_offline", "timestamp": _ts()},
        )

    async def fire_camera_online(self) -> None:
        if not self._can_fire("online"):
            return
        self._mark("online")
        await self._send(
            "🟢 Cámara reconectada",
            {"type": "camera_online", "timestamp": _ts()},
        )

    async def test(self) -> dict:
        """Send a test message to every configured channel."""
        text = "✅ Test de alertas — Tapo Dashboard funcionando"
        payload = {"type": "test", "timestamp": _ts()}
        results: dict[str, str] = {}
        if self.webhook_url:
            ok = await self._send_webhook(text, payload)
            results["webhook"] = "ok" if ok else "error"
        if self.telegram_token and self.telegram_chat_id:
            ok = await self._send_telegram(text)
            results["telegram"] = "ok" if ok else "error"
        if not results:
            results["warning"] = "no channels configured"
        return results

    @property
    def active_channels(self) -> list[str]:
        ch = []
        if self.webhook_url:
            ch.append("webhook")
        if self.telegram_token and self.telegram_chat_id:
            ch.append("telegram")
        return ch

    def status(self) -> dict:
        return {
            "active_channels": self.active_channels,
            "last_fired": {k: v.isoformat() for k, v in self._last_fire.items()},
            "cooldown_secs": self.cooldown_secs,
            "alert_on_intrusion": self.alert_on_intrusion,
            "alert_on_unknown": self.alert_on_unknown,
            "alert_on_detection": self.alert_on_detection,
            "count_threshold": self.count_threshold,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _can_fire(self, key: str) -> bool:
        last = self._last_fire.get(key)
        if last is None:
            return True
        return (datetime.datetime.now() - last).total_seconds() >= self.cooldown_secs

    def _mark(self, key: str) -> None:
        self._last_fire[key] = datetime.datetime.now()

    async def _send(self, text: str, payload: dict) -> None:
        tasks = []
        if self.webhook_url:
            tasks.append(self._send_webhook(text, payload))
        if self.telegram_token and self.telegram_chat_id:
            tasks.append(self._send_telegram(text))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("Alert send error: %s", r)

    async def _send_webhook(self, text: str, payload: dict) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(self.webhook_url, json=payload)
                r.raise_for_status()
            logger.info("Webhook alert sent: %s", payload.get("type"))
            return True
        except Exception as exc:
            logger.warning("Webhook alert failed: %s", exc)
            return False

    async def _send_telegram(self, text: str) -> bool:
        url = _TELEGRAM_API.format(token=self.telegram_token)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(
                    url,
                    json={"chat_id": self.telegram_chat_id, "text": text},
                )
                r.raise_for_status()
            logger.info("Telegram alert sent")
            return True
        except Exception as exc:
            logger.warning("Telegram alert failed: %s", exc)
            return False


def _ts(dt: datetime.datetime | None = None) -> str:
    return (dt or datetime.datetime.now()).isoformat(timespec="seconds")
