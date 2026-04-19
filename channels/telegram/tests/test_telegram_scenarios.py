"""Scenario-based tests for Telegram bot.py helper functions and mini-app logic.

Covers: has_rich_content, needs_mini_app, detect_content_type, extract_title,
artifact_markup, rich_content_markup, escape_markdown_v2, and _has_calendar_content.
"""

from __future__ import annotations

from unittest.mock import patch

from marcel_core.channels.telegram.bot import (
    _has_calendar_content,
    artifact_markup,
    detect_content_type,
    escape_markdown_v2,
    extract_title,
    has_rich_content,
    needs_mini_app,
    rich_content_markup,
)


class TestRichContentDetection:
    def test_table_detected(self):
        text = '| Name | Score |\n| Alice | 95 |'
        assert has_rich_content(text) is True

    def test_checklist_detected(self):
        text = '- [ ] Buy milk\n- [x] Buy eggs'
        assert has_rich_content(text) is True

    def test_calendar_detected(self):
        text = '📅 **Meeting** Monday April 14\n10:00–12:00 Team standup\n14:00–15:00 1:1 with Bob'
        assert has_rich_content(text) is True

    def test_plain_text_not_rich(self):
        assert has_rich_content('Just a normal message') is False


class TestNeedsMiniApp:
    def test_checklist_needs_app(self):
        text = '- [ ] Task one\n- [x] Task two'
        assert needs_mini_app(text) is True

    def test_table_does_not_need_app(self):
        text = '| Col | Val |\n| A | 1 |'
        assert needs_mini_app(text) is False

    def test_plain_does_not_need_app(self):
        assert needs_mini_app('Hello') is False


class TestDetectContentType:
    def test_calendar(self):
        text = '📅 **Event** Monday April 14\n10:00–12:00 Meeting\n14:00–15:00 Call'
        assert detect_content_type(text) == 'calendar'

    def test_checklist(self):
        text = '- [ ] Item 1\n- [x] Item 2'
        assert detect_content_type(text) == 'checklist'

    def test_markdown(self):
        assert detect_content_type('Just text') == 'markdown'


class TestExtractTitle:
    def test_bold_header(self):
        text = '**Morning Digest** for Monday\nMore content'
        assert extract_title(text) == 'Morning Digest'

    def test_emoji_stripped(self):
        text = '📅 **Weekly Events**\nStuff'
        title = extract_title(text)
        assert 'Weekly Events' in title

    def test_fallback_to_first_line(self):
        text = 'First line content\nSecond line'
        assert extract_title(text) == 'First line content'

    def test_hash_header_fallback(self):
        text = '# My Title\nBody'
        assert extract_title(text) == 'My Title'

    def test_empty_text(self):
        assert extract_title('') == 'Rich content'


class TestArtifactMarkup:
    def test_returns_markup_with_url(self):
        with patch('marcel_core.channels.telegram.bot._public_url', return_value='https://marcel.app'):
            result = artifact_markup('abc123')
        assert result is not None
        assert 'abc123' in str(result)

    def test_returns_none_without_url(self):
        with patch('marcel_core.channels.telegram.bot._public_url', return_value=None):
            assert artifact_markup('abc123') is None


class TestRichContentMarkup:
    def test_with_conversation_and_turn(self):
        with patch('marcel_core.channels.telegram.bot._public_url', return_value='https://marcel.app'):
            result = rich_content_markup(conversation_id='conv-1', turn=3)
        assert result is not None
        assert 'conv-1' in str(result)
        assert 'turn=3' in str(result)

    def test_without_url(self):
        with patch('marcel_core.channels.telegram.bot._public_url', return_value=None):
            assert rich_content_markup() is None

    def test_with_url_no_conversation(self):
        with patch('marcel_core.channels.telegram.bot._public_url', return_value='https://marcel.app'):
            result = rich_content_markup()
        assert result is not None


class TestEscapeMarkdownV2:
    def test_escapes_special_chars(self):
        result = escape_markdown_v2('Hello *world* [link](url)')
        assert '\\*' in result
        assert '\\[' in result
        assert '\\(' in result

    def test_plain_text_unchanged(self):
        assert escape_markdown_v2('hello') == 'hello'


class TestCalendarContent:
    def test_time_range_pattern(self):
        assert _has_calendar_content('Meeting 10:00–12:00 and 14:00-15:00') is True

    def test_single_time_not_enough(self):
        # Needs at least 2 pattern matches
        assert _has_calendar_content('See you at 10:00') is False

    def test_month_and_time(self):
        assert _has_calendar_content('April 14 meeting at **10:00**') is True
