"""Telegram channel integration for Marcel.

Exposes a FastAPI router that receives webhook updates from the Telegram
Bot API and routes them through the Marcel agent loop.

Self-registers with :mod:`marcel_core.plugin.channels` at import time so the
kernel can resolve the channel uniformly through the plugin registry instead
of via direct imports.

Setup summary:
1. Create a bot via @BotFather and copy the token.
2. Set ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_USER_MAP`` in ``.env``.
3. Register the webhook: ``python -m marcel_core.channels.telegram.setup <public_url>``.

See ``docs/channels/telegram.md`` for the full setup guide.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from marcel_core.channels.adapter import ChannelCapabilities
from marcel_core.plugin import register_channel

from .webhook import router

log = logging.getLogger(__name__)


class _TelegramPlugin:
    """Channel plugin for Telegram.

    Wraps the ``bot``/``sessions``/``formatting`` helpers so the rest of the
    kernel can push messages, photos, and artifact links through the plugin
    surface without importing telegram internals directly.
    """

    name = 'telegram'
    capabilities = ChannelCapabilities(
        markdown=True,
        rich_ui=True,
        streaming=True,
        progress_updates=True,
        attachments=True,
    )

    @property
    def router(self) -> APIRouter | None:
        return router

    async def send_message(self, user_slug: str, text: str) -> bool:
        from . import bot, sessions
        from .formatting import markdown_to_telegram_html

        chat_id = sessions.get_chat_id(user_slug)
        if not chat_id:
            return False
        await bot.send_message(int(chat_id), markdown_to_telegram_html(text))
        return True

    async def send_photo(
        self,
        user_slug: str,
        image_bytes: bytes,
        caption: str | None = None,
    ) -> bool:
        from . import bot, sessions

        chat_id = sessions.get_chat_id(user_slug)
        if not chat_id:
            return False
        await bot.send_photo(int(chat_id), image_bytes, caption=caption or '')
        return True

    async def send_artifact_link(
        self,
        user_slug: str,
        artifact_id: str,
        title: str,
    ) -> bool:
        from . import bot, sessions
        from .formatting import escape_html

        chat_id = sessions.get_chat_id(user_slug)
        if not chat_id:
            return False
        markup = bot.artifact_markup(artifact_id)
        if markup is None:
            log.warning(
                '[telegram:send_artifact_link] MARCEL_PUBLIC_URL not set; cannot send Mini App button for artifact %s',
                artifact_id,
            )
            return False
        caption = f'<b>{escape_html(title)}</b>'
        await bot.send_message(int(chat_id), caption, reply_markup=markup)
        return True

    def resolve_user_slug(self, external_id: str) -> str | None:
        from . import sessions

        return sessions.get_user_slug(external_id)


_plugin = _TelegramPlugin()
register_channel(_plugin)

__all__ = ['router']
