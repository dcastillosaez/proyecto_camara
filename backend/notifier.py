"""Notification dispatcher — pure I/O executor for Telegram and webhook delivery.

WHEN to alert lives in config/rules.yaml (backend.events.rules.RuleEngine), not
here. This module only knows how to send a message on a channel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TELEGRAM_PHOTO_API = "https://api.telegram.org/bot{token}/sendPhoto"


@dataclass
class Notifier:
    webhook_url: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @property
    def active_channels(self) -> list[str]:
        ch = []
        if self.webhook_url:
            ch.append("webhook")
        if self.telegram_token and self.telegram_chat_id:
            ch.append("telegram")
        return ch

    async def send_telegram(self, text: str, image: bytes | None = None) -> bool:
        if not (self.telegram_token and self.telegram_chat_id):
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                if image is not None:
                    url = _TELEGRAM_PHOTO_API.format(token=self.telegram_token)
                    r = await client.post(
                        url,
                        data={"chat_id": self.telegram_chat_id, "caption": text},
                        files={"photo": ("snapshot.jpg", image, "image/jpeg")},
                    )
                else:
                    url = _TELEGRAM_API.format(token=self.telegram_token)
                    r = await client.post(url, json={"chat_id": self.telegram_chat_id, "text": text})
                r.raise_for_status()
            logger.info("Telegram alert sent")
            return True
        except Exception as exc:
            logger.warning("Telegram alert failed: %s", exc)
            return False

    async def send_webhook(self, payload: dict) -> bool:
        if not self.webhook_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(self.webhook_url, json=payload)
                r.raise_for_status()
            logger.info("Webhook alert sent")
            return True
        except Exception as exc:
            logger.warning("Webhook alert failed: %s", exc)
            return False

    async def test(self) -> dict:
        """Send a test message to every configured channel."""
        text = "Test de alertas - Tapo Dashboard funcionando"
        results: dict[str, str] = {}
        if self.webhook_url:
            results["webhook"] = "ok" if await self.send_webhook({"type": "test"}) else "error"
        if self.telegram_token and self.telegram_chat_id:
            results["telegram"] = "ok" if await self.send_telegram(text) else "error"
        if not results:
            results["warning"] = "no channels configured"
        return results
