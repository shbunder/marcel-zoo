"""Markdown-to-Telegram-HTML conversion and calendar formatting.

Converts standard markdown (as output by Claude) to the HTML subset
supported by the Telegram Bot API.  Also provides calendar-specific
formatting with expandable blockquotes and pagination for day navigation.

Telegram HTML supports: <b>, <i>, <u>, <s>, <code>, <pre>,
<a href="...">, <blockquote>, <blockquote expandable>, <tg-spoiler>.
No <table>, <div>, <img>, <h1>, etc.
"""

import re
from dataclasses import dataclass

from marcel_core.config import settings

# ---------------------------------------------------------------------------
# HTML escaping
# ---------------------------------------------------------------------------


def escape_html(text: str) -> str:
    """Escape ``&``, ``<``, ``>`` for safe use inside Telegram HTML."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ---------------------------------------------------------------------------
# Markdown → Telegram HTML
# ---------------------------------------------------------------------------

# Regex for fenced code blocks: ```lang\n...\n```
_CODE_BLOCK_RE = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)

# Regex for inline code: `...`
_INLINE_CODE_RE = re.compile(r'`([^`\n]+)`')

# Counters for placeholder uniqueness
_placeholder_counter = 0


def _next_placeholder(prefix: str) -> str:
    global _placeholder_counter
    _placeholder_counter += 1
    return f'\x00{prefix}{_placeholder_counter}\x00'


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard markdown to Telegram-safe HTML.

    Processing order protects code content from being mangled:
    1. Extract code blocks → placeholders
    2. Extract inline code → placeholders
    3. Escape HTML entities in remaining text
    4. Convert markdown formatting to HTML tags
    5. Re-insert code blocks and inline code
    """
    global _placeholder_counter
    _placeholder_counter = 0

    placeholders: dict[str, str] = {}

    # 1. Extract fenced code blocks
    def _sub_code_block(m: re.Match) -> str:
        lang = m.group(1)
        code = escape_html(m.group(2).rstrip('\n'))
        ph = _next_placeholder('CB')
        if lang:
            placeholders[ph] = f'<pre><code class="language-{lang}">{code}</code></pre>'
        else:
            placeholders[ph] = f'<pre>{code}</pre>'
        return ph

    text = _CODE_BLOCK_RE.sub(_sub_code_block, text)

    # 2. Extract inline code
    def _sub_inline_code(m: re.Match) -> str:
        code = escape_html(m.group(1))
        ph = _next_placeholder('IC')
        placeholders[ph] = f'<code>{code}</code>'
        return ph

    text = _INLINE_CODE_RE.sub(_sub_inline_code, text)

    # 3. Escape HTML entities in remaining text
    text = escape_html(text)

    # 4. Convert markdown formatting

    # Headers: # ... → <b>...</b>
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    # Bold: **...** → <b>...</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

    # Italic: *...* → <i>...</i> (but not **)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<i>\1</i>', text)

    # Strikethrough: ~~...~~ → <s>...</s>
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # Links: [text](url) → <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Blockquotes: lines starting with > → <blockquote>...</blockquote>
    text = _convert_blockquotes(text)

    # Tables: flatten to readable lines
    text = _convert_tables(text)

    # 5. Re-insert placeholders
    for ph, html in placeholders.items():
        text = text.replace(ph, html)

    return text.strip()


def _convert_blockquotes(text: str) -> str:
    """Convert ``> ...`` lines into ``<blockquote>...</blockquote>``."""
    lines = text.split('\n')
    result: list[str] = []
    quote_lines: list[str] = []

    def _flush_quote() -> None:
        if quote_lines:
            content = '\n'.join(quote_lines)
            result.append(f'<blockquote>{content}</blockquote>')
            quote_lines.clear()

    for line in lines:
        if line.startswith('&gt; '):
            # > was escaped to &gt; in step 3
            quote_lines.append(line[5:])
        elif line.startswith('&gt;'):
            quote_lines.append(line[4:])
        else:
            _flush_quote()
            result.append(line)

    _flush_quote()
    return '\n'.join(result)


def _convert_tables(text: str) -> str:
    """Flatten markdown tables to readable plain text.

    Telegram HTML has no table support, so we convert:
    ``| Col1 | Col2 |`` rows into ``Col1 — Col2`` lines,
    skipping the separator row (``|---|---|``).
    """
    lines = text.split('\n')
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip separator rows
        if re.match(r'^\|[\s\-:|]+\|$', stripped):
            continue
        if '|' in stripped and stripped.startswith('|') and stripped.endswith('|'):
            cells = [c.strip() for c in stripped.split('|') if c.strip()]
            result.append(' — '.join(cells))
        else:
            result.append(line)
    return '\n'.join(result)


def strip_html_tags(text: str) -> str:
    """Remove HTML tags for plain-text fallback."""
    return re.sub(r'<[^>]+>', '', text)


# ---------------------------------------------------------------------------
# Calendar day-group parsing
# ---------------------------------------------------------------------------

# Date header pattern — matches Marcel's varied date formats:
# "📅 Today — Friday Apr 3", "Saturday 4 & Sunday 5 April",
# "Weekend Apr 4–5", "Monday Apr 6 onwards", "Ongoing all week"
_DATE_HEADER_RE = re.compile(
    r'(?:^|\n)\s*\*{0,2}[\U0001F4C5\U0001F5D3\U0001F3D5\U0001F4DA\U0001F3D6]*\s*'
    r'(?:'
    r'(?:Today|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*)[\s,]*'
    r'(?:\d{1,2}[\s&,\u2013\-]*)*'
    r'(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*)?'
    r'|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}'
    r'|'
    r'(?:Ongoing|Also\s+still)'
    r')',
    re.IGNORECASE,
)


@dataclass
class DayGroup:
    """A single day's header and content lines."""

    header: str
    content: str


def parse_day_groups(text: str) -> list[DayGroup] | None:
    """Split calendar markdown into per-day groups.

    Returns ``None`` if the text doesn't contain recognisable date headers
    with event content below them.
    """
    lines = text.split('\n')
    groups: list[DayGroup] = []
    current_header: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if _DATE_HEADER_RE.match(line.strip()):
            # Save previous group
            if current_header is not None and current_lines:
                content = '\n'.join(current_lines).strip()
                if content:
                    groups.append(DayGroup(header=current_header, content=content))
            # Start new group
            current_header = line.strip().replace('**', '').strip()
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)

    # Don't forget the last group
    if current_header is not None and current_lines:
        content = '\n'.join(current_lines).strip()
        if content:
            groups.append(DayGroup(header=current_header, content=content))

    return groups if len(groups) >= 1 else None


# ---------------------------------------------------------------------------
# Calendar page formatting
# ---------------------------------------------------------------------------

DAYS_PER_PAGE = 3


def format_calendar_page(groups: list[DayGroup], page: int) -> str:
    """Format one page of calendar output as Telegram HTML.

    Each day group becomes a bold header + expandable blockquote:

    .. code-block:: html

        <b>Today — Friday Apr 3</b>
        <blockquote expandable>
        event content...
        </blockquote>
    """
    start = page * DAYS_PER_PAGE
    end = min(start + DAYS_PER_PAGE, len(groups))
    page_groups = groups[start:end]

    parts: list[str] = []
    for group in page_groups:
        header_html = f'<b>{escape_html(group.header)}</b>'
        content_html = markdown_to_telegram_html(group.content)
        parts.append(f'{header_html}\n<blockquote expandable>{content_html}</blockquote>')

    return '\n\n'.join(parts)


def calendar_nav_markup(
    conversation_id: str,
    page: int,
    total_pages: int,
    *,
    web_app_url: str | None = None,
) -> dict:
    """Build ``InlineKeyboardMarkup`` with prev/next buttons + optional web_app button.

    ``callback_data`` format: ``cal:{conversation_id}:{page}``
    """
    nav_row: list[dict] = []

    if page > 0:
        nav_row.append(
            {
                'text': '\u25c0 Prev',
                'callback_data': f'cal:{conversation_id}:{page - 1}',
            }
        )

    nav_row.append(
        {
            'text': f'{page + 1}/{total_pages}',
            'callback_data': 'noop',
        }
    )

    if page < total_pages - 1:
        nav_row.append(
            {
                'text': 'Next \u25b6',
                'callback_data': f'cal:{conversation_id}:{page + 1}',
            }
        )

    rows: list[list[dict]] = [nav_row]

    if web_app_url:
        rows.append([{'text': '\u2728 View in app', 'web_app': {'url': web_app_url}}])

    return {'inline_keyboard': rows}


def _public_url() -> str | None:
    """Return the configured public URL, or ``None`` if not set."""
    return settings.marcel_public_url or None


def web_app_url_for(
    conversation_id: str | None = None,
    turn: int | None = None,
    artifact_id: str | None = None,
) -> str | None:
    """Return the Mini App URL for an artifact or conversation, or ``None``.

    When *artifact_id* is provided it takes precedence over the
    conversation/turn parameters.
    """
    url = _public_url()
    if not url:
        return None
    if artifact_id:
        return f'{url}?artifact={artifact_id}'
    if conversation_id:
        result = f'{url}?conversation={conversation_id}'
        if turn is not None:
            result += f'&turn={turn}'
        return result
    return url
