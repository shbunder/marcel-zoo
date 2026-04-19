"""Tests for Telegram formatting module.

Covers markdown→HTML conversion, calendar day-group parsing,
calendar page formatting, and navigation markup generation.
"""

from marcel_core.channels.telegram.formatting import (
    DayGroup,
    calendar_nav_markup,
    escape_html,
    format_calendar_page,
    markdown_to_telegram_html,
    parse_day_groups,
    strip_html_tags,
    web_app_url_for,
)
from marcel_core.config import settings

# ---------------------------------------------------------------------------
# escape_html
# ---------------------------------------------------------------------------


class TestEscapeHtml:
    def test_escapes_ampersand(self):
        assert escape_html('a & b') == 'a &amp; b'

    def test_escapes_angle_brackets(self):
        assert escape_html('<div>') == '&lt;div&gt;'

    def test_plain_text_unchanged(self):
        assert escape_html('hello world') == 'hello world'

    def test_empty_string(self):
        assert escape_html('') == ''

    def test_all_entities(self):
        assert escape_html('a & b < c > d') == 'a &amp; b &lt; c &gt; d'


# ---------------------------------------------------------------------------
# strip_html_tags
# ---------------------------------------------------------------------------


class TestStripHtmlTags:
    def test_strips_simple_tags(self):
        assert strip_html_tags('<b>bold</b>') == 'bold'

    def test_strips_nested_tags(self):
        assert strip_html_tags('<b><i>nested</i></b>') == 'nested'

    def test_preserves_plain_text(self):
        assert strip_html_tags('no tags here') == 'no tags here'

    def test_strips_expandable_blockquote(self):
        assert strip_html_tags('<blockquote expandable>content</blockquote>') == 'content'


# ---------------------------------------------------------------------------
# markdown_to_telegram_html
# ---------------------------------------------------------------------------


class TestMarkdownToTelegramHtml:
    def test_bold(self):
        assert '<b>bold text</b>' in markdown_to_telegram_html('**bold text**')

    def test_italic(self):
        assert '<i>italic</i>' in markdown_to_telegram_html('*italic*')

    def test_bold_not_confused_with_italic(self):
        result = markdown_to_telegram_html('**bold** and *italic*')
        assert '<b>bold</b>' in result
        assert '<i>italic</i>' in result

    def test_strikethrough(self):
        assert '<s>struck</s>' in markdown_to_telegram_html('~~struck~~')

    def test_inline_code(self):
        assert '<code>code</code>' in markdown_to_telegram_html('`code`')

    def test_code_block(self):
        result = markdown_to_telegram_html('```python\nprint("hi")\n```')
        assert '<pre>' in result
        assert 'print' in result

    def test_code_block_html_escaped(self):
        result = markdown_to_telegram_html('```\na < b && c > d\n```')
        assert '&lt;' in result
        assert '&amp;' in result

    def test_link(self):
        result = markdown_to_telegram_html('[click](https://example.com)')
        assert '<a href="https://example.com">click</a>' in result

    def test_header(self):
        result = markdown_to_telegram_html('## My Header')
        assert '<b>My Header</b>' in result

    def test_blockquote(self):
        result = markdown_to_telegram_html('> quoted text')
        assert '<blockquote>quoted text</blockquote>' in result

    def test_table_flattened(self):
        table = '| Name | Value |\n|---|---|\n| foo | bar |'
        result = markdown_to_telegram_html(table)
        assert '|' not in result
        assert 'foo' in result
        assert 'bar' in result

    def test_html_entities_escaped(self):
        result = markdown_to_telegram_html('a < b & c > d')
        assert '&lt;' in result
        assert '&amp;' in result
        assert '&gt;' in result

    def test_code_not_double_escaped(self):
        result = markdown_to_telegram_html('`a < b`')
        assert '&lt;' in result
        assert '&amp;lt;' not in result

    def test_emoji_preserved(self):
        result = markdown_to_telegram_html('Hello 👋 world')
        assert '👋' in result

    def test_real_calendar_snippet(self):
        text = '**📅 Today — Friday Apr 3**\n\n- 🪒 **Afspraak kapper** — 10:00–12:00 @ Kapsalon'
        result = markdown_to_telegram_html(text)
        assert '<b>' in result
        assert 'Afspraak kapper' in result


# ---------------------------------------------------------------------------
# parse_day_groups
# ---------------------------------------------------------------------------


class TestParseDayGroups:
    def test_returns_none_for_non_calendar(self):
        assert parse_day_groups('Hello, how are you?') is None

    def test_parses_single_day(self):
        text = '**📅 Today — Friday Apr 3**\n- 🪒 **Afspraak kapper** — 10:00–12:00\n- 🏀 **Basketball** — 18:00'
        groups = parse_day_groups(text)
        assert groups is not None
        assert len(groups) == 1
        assert 'Today' in groups[0].header
        assert 'kapper' in groups[0].content

    def test_parses_multiple_days(self):
        text = (
            '**📅 Today — Friday Apr 3**\n'
            '- Event 1\n'
            '\n'
            '**📅 Saturday 4 & Sunday 5 April**\n'
            '- Event 2\n'
            '\n'
            '**📅 Monday Apr 6 onwards**\n'
            '- Event 3'
        )
        groups = parse_day_groups(text)
        assert groups is not None
        assert len(groups) == 3

    def test_real_marcel_output(self):
        text = (
            '**📅 Today — Thursday Apr 3**\n\n'
            '- 🪒 **Afspraak kapper** — 10:00–12:00 @ Kapsalon\n\n'
            '**📅 Saturday 4 & Sunday 5 April**\n\n'
            '🏕 **Weekend VdB** *(Kids)*\n'
            'Description with **Friday 16:00** start\n\n'
            '**📅 Monday Apr 6 onwards**\n\n'
            '- 📚 **School starts** — 08:30\n'
            '- 🏀 **Basketball training** — 18:00–19:30'
        )
        groups = parse_day_groups(text)
        assert groups is not None
        assert len(groups) == 3
        assert 'Thursday' in groups[0].header
        assert 'Saturday' in groups[1].header
        assert 'Monday' in groups[2].header


# ---------------------------------------------------------------------------
# format_calendar_page
# ---------------------------------------------------------------------------


class TestFormatCalendarPage:
    def test_single_group(self):
        groups = [DayGroup(header='Today', content='- Event 1\n- Event 2')]
        html = format_calendar_page(groups, page=0)
        assert '<b>' in html
        assert '<blockquote expandable>' in html
        assert 'Event 1' in html

    def test_pagination(self):
        groups = [DayGroup(header=f'Day {i}', content=f'Event {i}') for i in range(7)]
        page0 = format_calendar_page(groups, page=0)
        page1 = format_calendar_page(groups, page=1)
        page2 = format_calendar_page(groups, page=2)

        assert 'Day 0' in page0
        assert 'Day 2' in page0
        assert 'Day 3' not in page0

        assert 'Day 3' in page1
        assert 'Day 5' in page1

        assert 'Day 6' in page2


# ---------------------------------------------------------------------------
# calendar_nav_markup
# ---------------------------------------------------------------------------


class TestCalendarNavMarkup:
    def test_first_page_no_prev(self):
        markup = calendar_nav_markup('2026-04-03T14-32', page=0, total_pages=3)
        nav_row = markup['inline_keyboard'][0]
        texts = [b['text'] for b in nav_row]
        assert any('Prev' in t for t in texts) is False
        assert any('Next' in t for t in texts) is True

    def test_last_page_no_next(self):
        markup = calendar_nav_markup('2026-04-03T14-32', page=2, total_pages=3)
        nav_row = markup['inline_keyboard'][0]
        texts = [b['text'] for b in nav_row]
        assert any('Prev' in t for t in texts) is True
        assert any('Next' in t for t in texts) is False

    def test_middle_page_has_both(self):
        markup = calendar_nav_markup('2026-04-03T14-32', page=1, total_pages=3)
        nav_row = markup['inline_keyboard'][0]
        texts = [b['text'] for b in nav_row]
        assert any('Prev' in t for t in texts) is True
        assert any('Next' in t for t in texts) is True

    def test_callback_data_format(self):
        markup = calendar_nav_markup('2026-04-03T14-32', page=1, total_pages=3)
        nav_row = markup['inline_keyboard'][0]
        prev_btn = [b for b in nav_row if 'Prev' in b['text']][0]
        assert prev_btn['callback_data'] == 'cal:2026-04-03T14-32:0'

    def test_callback_data_within_64_bytes(self):
        markup = calendar_nav_markup('2026-04-03T14-32', page=99, total_pages=100)
        for row in markup['inline_keyboard']:
            for btn in row:
                if 'callback_data' in btn:
                    assert len(btn['callback_data'].encode()) <= 64

    def test_web_app_button_included(self):
        markup = calendar_nav_markup(
            '2026-04-03T14-32',
            page=0,
            total_pages=2,
            web_app_url='https://marcel-bot.com?conversation=2026-04-03T14-32',
        )
        assert len(markup['inline_keyboard']) == 2
        app_btn = markup['inline_keyboard'][1][0]
        assert 'web_app' in app_btn

    def test_no_web_app_button_when_no_url(self):
        markup = calendar_nav_markup('2026-04-03T14-32', page=0, total_pages=2)
        assert len(markup['inline_keyboard']) == 1


# ---------------------------------------------------------------------------
# web_app_url_for
# ---------------------------------------------------------------------------


class TestWebAppUrlFor:
    def test_returns_none_without_env(self, monkeypatch):
        # autouse fixture already resets settings.marcel_public_url to None
        assert web_app_url_for('conv-1') is None

    def test_returns_url_with_conversation(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', 'https://marcel-bot.com')
        assert web_app_url_for('conv-1') == 'https://marcel-bot.com?conversation=conv-1'

    def test_returns_base_url_without_conversation(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', 'https://marcel-bot.com')
        assert web_app_url_for() == 'https://marcel-bot.com'
