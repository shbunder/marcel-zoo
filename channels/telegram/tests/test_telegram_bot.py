"""Tests for channels/telegram/bot.py — HTTP client functions and Mini App helpers."""

import pytest
import respx
from httpx import Response

from marcel_core.channels.telegram.bot import (
    _has_calendar_content,
    _token,
    answer_callback_query,
    delete_webhook,
    edit_message_text,
    has_rich_content,
    rich_content_markup,
    send_message,
    set_menu_button,
    set_webhook,
)
from marcel_core.config import settings

# ---------------------------------------------------------------------------
# _token()
# ---------------------------------------------------------------------------


class TestToken:
    def test_raises_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', '')
        with pytest.raises(RuntimeError, match='TELEGRAM_BOT_TOKEN'):
            _token()

    def test_returns_token_when_set(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'my-token')
        assert _token() == 'my-token'


# ---------------------------------------------------------------------------
# has_rich_content / _has_calendar_content
# ---------------------------------------------------------------------------


class TestHasRichContent:
    def test_detects_markdown_table(self):
        # Pattern requires 3 pipe chars: \|.+\|.+\|
        text = '| Name | Score | Rank |\n|---|---|---|\n| Alice | 95 | 1 |'
        assert has_rich_content(text) is True

    def test_detects_task_list(self):
        text = '- [x] Buy milk\n- [ ] Walk dog'
        assert has_rich_content(text) is True

    def test_plain_text_is_not_rich(self):
        assert has_rich_content('Hello, how are you?') is False

    def test_single_date_not_rich(self):
        # One pattern match is not enough for calendar detection
        assert has_rich_content('Meeting on April 3') is False

    def test_calendar_with_time_and_date_is_rich(self):
        text = 'Dentist appointment April 3 at 10:00–11:00'
        assert has_rich_content(text) is True


class TestHasCalendarContent:
    def test_time_range_counts(self):
        text = '10:00–12:00 meeting and 14:00-15:00 call'
        assert _has_calendar_content(text) is True

    def test_two_patterns_needed(self):
        # Only one pattern (time range), no date name
        text = 'It happened at 10:00'
        assert _has_calendar_content(text) is False


# ---------------------------------------------------------------------------
# rich_content_markup
# ---------------------------------------------------------------------------


class TestRichContentMarkup:
    def test_returns_none_without_public_url(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', None)
        assert rich_content_markup() is None

    def test_returns_markup_with_url(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', 'https://my-bot.com')
        result = rich_content_markup()
        assert result is not None
        assert 'inline_keyboard' in result
        button = result['inline_keyboard'][0][0]
        assert button['web_app']['url'] == 'https://my-bot.com'

    def test_includes_conversation_id(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', 'https://my-bot.com')
        result = rich_content_markup(conversation_id='conv-1')
        assert result is not None
        url = result['inline_keyboard'][0][0]['web_app']['url']
        assert 'conversation=conv-1' in url

    def test_includes_turn(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', 'https://my-bot.com')
        result = rich_content_markup(conversation_id='conv-1', turn=3)
        assert result is not None
        url = result['inline_keyboard'][0][0]['web_app']['url']
        assert 'turn=3' in url


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_html_and_returns_message_id(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
            return_value=Response(200, json={'ok': True, 'result': {'message_id': 42}})
        )
        msg_id = await send_message(123, '<b>hello</b>')
        assert msg_id == 42

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_plain_text_on_failure(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        route = respx.post('https://api.telegram.org/bottest-token/sendMessage')
        route.side_effect = [
            Response(400, json={'ok': False, 'description': "Bad Request: can't parse HTML"}),
            Response(200, json={'ok': True, 'result': {'message_id': 99}}),
        ]
        msg_id = await send_message(123, '<invalid>html')
        assert msg_id == 99

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_when_both_attempts_fail(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
            return_value=Response(500, text='Internal Server Error')
        )
        with pytest.raises(RuntimeError, match='sendMessage failed'):
            await send_message(123, 'oops')

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_with_reply_markup(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
            return_value=Response(200, json={'ok': True, 'result': {'message_id': 7}})
        )
        markup = {'inline_keyboard': [[{'text': 'Click', 'callback_data': 'btn'}]]}
        msg_id = await send_message(123, 'hello', reply_markup=markup)
        assert msg_id == 7


# ---------------------------------------------------------------------------
# edit_message_text
# ---------------------------------------------------------------------------


class TestEditMessageText:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_true_on_success(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/editMessageText').mock(
            return_value=Response(200, json={'ok': True})
        )
        result = await edit_message_text(123, 42, 'updated text')
        assert result is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_plain_text(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        route = respx.post('https://api.telegram.org/bottest-token/editMessageText')
        route.side_effect = [
            Response(400, json={'ok': False}),
            Response(200, json={'ok': True}),
        ]
        result = await edit_message_text(123, 42, '<bad>html</bad>')
        assert result is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_false_when_both_fail(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/editMessageText').mock(
            return_value=Response(400, json={'ok': False})
        )
        result = await edit_message_text(123, 42, 'still failing')
        assert result is False


# ---------------------------------------------------------------------------
# answer_callback_query
# ---------------------------------------------------------------------------


class TestAnswerCallbackQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_ack(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/answerCallbackQuery').mock(
            return_value=Response(200, json={'ok': True})
        )
        # Should not raise
        await answer_callback_query('cq-123', text='Done!')

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_without_text(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/answerCallbackQuery').mock(
            return_value=Response(200, json={'ok': True})
        )
        await answer_callback_query('cq-456')


# ---------------------------------------------------------------------------
# set_webhook / delete_webhook
# ---------------------------------------------------------------------------


class TestSetWebhook:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sets_webhook(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/setWebhook').mock(
            return_value=Response(200, json={'ok': True})
        )
        result = await set_webhook('https://myhost.com/telegram/webhook', secret='sec')
        assert result == {'ok': True}

    @pytest.mark.asyncio
    @respx.mock
    async def test_deletes_webhook(self, monkeypatch):
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/deleteWebhook').mock(
            return_value=Response(200, json={'ok': True})
        )
        result = await delete_webhook()
        assert result == {'ok': True}


# ---------------------------------------------------------------------------
# set_menu_button
# ---------------------------------------------------------------------------


class TestSetMenuButton:
    @pytest.mark.asyncio
    async def test_returns_none_without_public_url(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', None)
        result = await set_menu_button()
        assert result is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_sets_menu_button(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', 'https://my-bot.com')
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        respx.post('https://api.telegram.org/bottest-token/setChatMenuButton').mock(
            return_value=Response(200, json={'ok': True})
        )
        result = await set_menu_button()
        assert result == {'ok': True}
