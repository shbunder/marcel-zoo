"""Telegram session state: maps chat IDs to Marcel users and tracks activity.

User linking is stored in ``profile.md`` frontmatter::

    ---
    role: admin
    telegram_chat_id: "556632386"
    ---

This keeps Telegram config with the rest of the user's data. To link a user,
call :func:`link_user`.

Conversation model: one continuous conversation per channel. No session
creation/destruction — the conversation lives forever, segmented and
summarized by the idle summarization system. Last-message timestamps are
tracked by the conversation channel metadata (``channel.meta.json``).
"""

from __future__ import annotations

from marcel_core.memory.conversation import ensure_channel, save_channel_meta
from marcel_core.storage.users import (
    find_user_by_telegram_chat_id,
    get_telegram_chat_id,
    set_telegram_chat_id,
)


def link_user(user_slug: str, chat_id: int | str) -> None:
    """Link a Marcel user to a Telegram chat ID.

    Writes the chat ID to ``profile.md`` frontmatter.
    Creates the user directory if it does not yet exist.
    """
    set_telegram_chat_id(user_slug, str(chat_id))


def get_user_slug(chat_id: int | str) -> str | None:
    """Return the Marcel user slug for a Telegram chat ID, or None if not linked."""
    return find_user_by_telegram_chat_id(chat_id)


def get_chat_id(user_slug: str) -> str | None:
    """Return the Telegram chat ID for a Marcel user slug, or None if not linked."""
    return get_telegram_chat_id(user_slug)


def touch_last_message(chat_id: int | str) -> None:
    """Update the last-message timestamp for a chat to now (UTC).

    Uses the conversation channel metadata (``channel.meta.json``) which
    already tracks ``last_active``. Ensures the telegram channel exists.
    """
    from datetime import datetime, timezone

    user_slug = get_user_slug(chat_id)
    if user_slug is None:
        return

    meta = ensure_channel(user_slug, 'telegram')
    meta.last_active = datetime.now(tz=timezone.utc)
    save_channel_meta(user_slug, 'telegram', meta)
