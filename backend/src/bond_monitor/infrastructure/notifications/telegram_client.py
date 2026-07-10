"""Telegram Bot API delivery."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    @property
    def configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def send_message(self, text: str) -> bool:
        if not self.configured:
            logger.warning("Telegram notifier is not configured")
            return False
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        response = httpx.post(
            url,
            json={
                "chat_id": self._chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=15.0,
        )
        if response.status_code != 200:
            logger.error("Telegram send failed: %s %s", response.status_code, response.text)
            return False
        return True
