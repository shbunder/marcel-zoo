"""Telegram Bot API client.

Provides a thin async wrapper around the Telegram Bot API endpoints.
Tries HTML parse mode first; falls back to plain text if Telegram
rejects the formatting.
"""

import re

import httpx

from .formatting import strip_html_tags
from marcel_core.config import settings

_API_BASE = 'https://api.telegram.org'

# Patterns that indicate the response contains rich content worth viewing in
# the Mini App (calendar events, task lists, markdown tables).
_RICH_TABLE_RE = re.compile(r'\|.+\|.+\|')
_RICH_TASKLIST_RE = re.compile(r'^- \[[ xX]\] ', re.MULTILINE)
# Calendar-style: flexible detection — calendar emoji, time patterns, or
# day/month names combined with event-like structure.
_RICH_CALENDAR_PATTERNS: list[re.Pattern[str]] = [
    # Time ranges: 10:00–12:00, 16:00-18:00
    re.compile(r'\d{1,2}:\d{2}\s*[–\-]\s*\d{1,2}:\d{2}'),
    # Standalone times in bold or after dash: **16:00**, — 10:00
    re.compile(r'(?:\*{1,2}|[—\-]\s*)\d{1,2}:\d{2}'),
    # Calendar/event emoji followed by bold text (event title pattern)
    re.compile(r'[📅🗓🏕📚🎂🎉⚠🚫]\s*\*{1,2}'),
    # Day names + month names nearby (within 30 chars)
    re.compile(
        r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday).{0,30}(?:January|February|March|April|May|June|July|August|September|October|November|December)',
        re.IGNORECASE,
    ),
    # Month + day number: "April 3", "Apr 6", "5 April"
    re.compile(
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*',
        re.IGNORECASE,
    ),
]

# Characters that must be escaped in Telegram MarkdownV2 (deprecated)
_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')


def escape_markdown_v2(text: str) -> str:
    """Escape a plain-text string for safe use inside a MarkdownV2 message.

    .. deprecated::
        Use :func:`escape_html` instead now that messages use HTML parse mode.
    """
    return _ESCAPE_RE.sub(r'\\\1', text)


def _token() -> str:
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is not set in the environment')
    return token


async def send_message(
    chat_id: int | str,
    text: str,
    *,
    parse_mode: str = 'HTML',
    reply_markup: dict | None = None,
) -> int | None:
    """Send a text message to a Telegram chat.

    Attempts delivery with HTML parse mode. If Telegram rejects the
    request (e.g. malformed markup), retries with plain text so the user
    always receives a response.

    Returns:
        The ``message_id`` of the sent message on success, or ``None``.
    """
    token = _token()
    url = f'{_API_BASE}/bot{token}/sendMessage'

    payload: dict = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        if resp.is_success:
            data = resp.json()
            return data.get('result', {}).get('message_id')

        # HTML rejected — retry as plain text so the user isn't left hanging
        plain_text = strip_html_tags(text) if parse_mode == 'HTML' else text
        plain_payload: dict = {'chat_id': chat_id, 'text': plain_text}
        if reply_markup:
            plain_payload['reply_markup'] = reply_markup
        plain_resp = await client.post(url, json=plain_payload)
        if not plain_resp.is_success:
            raise RuntimeError(f'Telegram sendMessage failed: {plain_resp.status_code} {plain_resp.text}')
        data = plain_resp.json()
        return data.get('result', {}).get('message_id')


async def edit_message_text(
    chat_id: int | str,
    message_id: int,
    text: str,
    *,
    parse_mode: str = 'HTML',
    reply_markup: dict | None = None,
) -> bool:
    """Edit an existing message's text.

    Same fallback strategy as :func:`send_message` — tries HTML first,
    falls back to plain text.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    token = _token()
    url = f'{_API_BASE}/bot{token}/editMessageText'

    payload: dict = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': parse_mode,
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        if resp.is_success:
            return True

        plain_text = strip_html_tags(text) if parse_mode == 'HTML' else text
        plain_payload: dict = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': plain_text,
        }
        if reply_markup:
            plain_payload['reply_markup'] = reply_markup
        plain_resp = await client.post(url, json=plain_payload)
        return plain_resp.is_success


async def send_photo(
    chat_id: int | str,
    photo: bytes | str,
    *,
    caption: str = '',
    parse_mode: str = 'HTML',
    reply_markup: dict | None = None,
) -> int | None:
    """Send a photo to a Telegram chat.

    Args:
        chat_id: The target chat ID.
        photo: Either raw bytes (file upload) or a file_id / URL string.
        caption: Optional caption text (supports HTML).
        parse_mode: Parse mode for caption.
        reply_markup: Optional inline keyboard markup.

    Returns:
        The ``message_id`` of the sent message on success, or ``None``.
    """
    token = _token()
    url = f'{_API_BASE}/bot{token}/sendPhoto'

    if isinstance(photo, bytes):
        # Upload as multipart form data
        data: dict = {'chat_id': str(chat_id)}
        if caption:
            data['caption'] = caption
            data['parse_mode'] = parse_mode
        if reply_markup:
            import json

            data['reply_markup'] = json.dumps(reply_markup)
        files = {'photo': ('chart.png', photo, 'image/png')}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data, files=files)
    else:
        # Send by file_id or URL
        payload: dict = {'chat_id': chat_id, 'photo': photo}
        if caption:
            payload['caption'] = caption
            payload['parse_mode'] = parse_mode
        if reply_markup:
            payload['reply_markup'] = reply_markup
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)

    if resp.is_success:
        result_data = resp.json()
        return result_data.get('result', {}).get('message_id')
    return None


async def answer_callback_query(callback_query_id: str, text: str = '') -> None:
    """Acknowledge a callback query to dismiss the loading spinner."""
    token = _token()
    url = f'{_API_BASE}/bot{token}/answerCallbackQuery'
    payload: dict = {'callback_query_id': callback_query_id}
    if text:
        payload['text'] = text
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)


async def set_webhook(url: str, *, secret: str = '') -> dict:
    """Register a webhook URL with the Telegram Bot API.

    Args:
        url: The public HTTPS URL Telegram should call for updates.
        secret: Optional secret token sent as ``X-Telegram-Bot-Api-Secret-Token``.

    Returns:
        The parsed JSON response from Telegram.
    """
    token = _token()
    payload: dict = {'url': url}
    if secret:
        payload['secret_token'] = secret

    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{_API_BASE}/bot{token}/setWebhook', json=payload)
        resp.raise_for_status()
        return resp.json()


async def delete_webhook() -> dict:
    """Deregister the current webhook (switches bot to polling mode).

    Returns:
        The parsed JSON response from Telegram.
    """
    token = _token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{_API_BASE}/bot{token}/deleteWebhook')
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Mini App helpers
# ---------------------------------------------------------------------------


def _public_url() -> str | None:
    """Return the configured public URL, or None if not set."""
    return settings.marcel_public_url or None


def _has_calendar_content(text: str) -> bool:
    """Return True if *text* looks like a calendar/event response."""
    # Require at least 2 pattern matches to avoid false positives on casual
    # mentions of dates or times.
    matches = sum(1 for p in _RICH_CALENDAR_PATTERNS if p.search(text))
    return matches >= 2


def has_rich_content(text: str) -> bool:
    """Return True if *text* contains rich formatting (calendars, tables, checklists)."""
    return bool(_RICH_TABLE_RE.search(text) or _RICH_TASKLIST_RE.search(text) or _has_calendar_content(text))


def needs_mini_app(text: str) -> bool:
    """Return True if the content genuinely benefits from the Mini App viewer.

    Only interactive content (checklists) warrants a "View in app" button.
    Calendars and tables render well enough in Telegram's native HTML.
    """
    return bool(_RICH_TASKLIST_RE.search(text))


_BUTTON_LABELS = {
    'calendar': '📅 Show events',
    'checklist': '☑️ Show checklist',
}


def detect_content_type(text: str) -> str:
    """Classify rich content as ``'calendar'``, ``'checklist'``, or ``'markdown'``."""
    if _has_calendar_content(text):
        return 'calendar'
    if _RICH_TASKLIST_RE.search(text):
        return 'checklist'
    return 'markdown'


def extract_title(text: str) -> str:
    """Extract a short title from the first bold header or first line."""
    # Try first bold header
    m = re.search(r'\*\*(.+?)\*\*', text)
    if m:
        title = m.group(1).strip()
        # Strip leading emoji
        title = re.sub(r'^[\U0001F300-\U0001FAFF\U00002702-\U000027B0\s]+', '', title)
        if title:
            return title[:60]
    # Fall back to first non-empty line
    for line in text.split('\n'):
        line = line.strip().lstrip('#').strip()
        if line:
            return line[:60]
    return 'Rich content'


def artifact_markup(artifact_id: str) -> dict | None:
    """Return an InlineKeyboardMarkup that opens the Mini App for a specific artifact."""
    url = _public_url()
    if not url:
        return None
    app_url = f'{url}?artifact={artifact_id}'
    return {
        'inline_keyboard': [[{'text': '✨ View in app', 'web_app': {'url': app_url}}]],
    }


def rich_content_markup(conversation_id: str | None = None, turn: int | None = None) -> dict | None:
    """Return an InlineKeyboardMarkup that opens the Mini App, or None.

    .. deprecated::
        Use :func:`artifact_markup` for new messages. This function is kept
        for backward compatibility with calendar navigation callbacks.
    """
    url = _public_url()
    if not url:
        return None
    app_url = url
    if conversation_id:
        app_url = f'{url}?conversation={conversation_id}'
        if turn is not None:
            app_url += f'&turn={turn}'
    return {
        'inline_keyboard': [[{'text': '✨ View in app', 'web_app': {'url': app_url}}]],
    }


async def set_menu_button() -> dict | None:
    """Set the bot menu button to open the Mini App.

    Requires ``MARCEL_PUBLIC_URL`` to be set. Returns ``None`` if not
    configured, otherwise the Telegram API response.
    """
    url = _public_url()
    if not url:
        return None
    token = _token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f'{_API_BASE}/bot{token}/setChatMenuButton',
            json={'menu_button': {'type': 'web_app', 'text': 'Open Marcel', 'web_app': {'url': url}}},
        )
        resp.raise_for_status()
        return resp.json()
