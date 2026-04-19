"""Scenario-based tests for the Telegram webhook handler.

Tests _format_response, _run_forget, and the webhook endpoint through
realistic Telegram update payloads. All external API calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marcel_core.channels.telegram.webhook import (
    _format_response,
    _handle_callback_query,
    _process_assistant_message,
    _process_with_delayed_ack,
    _run_forget,
    router,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# _format_response
# ---------------------------------------------------------------------------


class TestFormatResponse:
    def test_plain_text_response(self):
        html, markup = _format_response('Hello world', 'conv-1')
        assert 'Hello' in html
        assert markup is None  # no rich content

    def test_checklist_response(self):
        text = '- [ ] Buy milk\n- [x] Buy eggs'
        with patch('marcel_core.channels.telegram.webhook.bot') as mock_bot:
            mock_bot.has_rich_content.return_value = True
            mock_bot.needs_mini_app.return_value = True
            mock_bot.detect_content_type.return_value = 'checklist'
            mock_bot.artifact_markup.return_value = {'inline_keyboard': [[{'text': 'View'}]]}
            html, markup = _format_response(text, 'conv-1', artifact_id='art-123')
        assert markup is not None

    def test_calendar_multi_page(self):
        """When day_groups exceed DAYS_PER_PAGE, calendar nav is shown."""
        with (
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.parse_day_groups') as mock_parse,
            patch('marcel_core.channels.telegram.webhook.format_calendar_page', return_value='<b>Page 1</b>'),
            patch('marcel_core.channels.telegram.webhook.calendar_nav_markup', return_value={'inline_keyboard': []}),
        ):
            mock_bot.has_rich_content.return_value = True
            mock_bot.needs_mini_app.return_value = False
            # Return more groups than DAYS_PER_PAGE (default is 3)
            mock_parse.return_value = [MagicMock() for _ in range(10)]
            html, markup = _format_response('calendar text', 'conv-1')
        assert '<b>Page 1</b>' in html
        assert markup is not None

    def test_calendar_single_page(self):
        with (
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.parse_day_groups') as mock_parse,
            patch('marcel_core.channels.telegram.webhook.format_calendar_page', return_value='<b>Events</b>'),
        ):
            mock_bot.has_rich_content.return_value = True
            mock_bot.needs_mini_app.return_value = False
            mock_parse.return_value = [MagicMock()]  # single group
            html, markup = _format_response('calendar', 'conv-1')
        assert '<b>Events</b>' in html
        assert markup is None


# ---------------------------------------------------------------------------
# _run_forget
# ---------------------------------------------------------------------------


class TestRunForget:
    @pytest.mark.asyncio
    async def test_successful_forget(self):
        with (
            patch(
                'marcel_core.channels.telegram.webhook.summarize_active_segment',
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_bot.send_message = AsyncMock()
            await _run_forget(123, 'alice')
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_forget(self):
        with (
            patch(
                'marcel_core.channels.telegram.webhook.summarize_active_segment',
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_bot.send_message = AsyncMock()
            await _run_forget(123, 'alice')
        assert 'failed' in mock_bot.send_message.call_args[0][1].lower() or 'failed' in str(
            mock_bot.send_message.call_args
        )

    @pytest.mark.asyncio
    async def test_exception_during_forget(self):
        with (
            patch(
                'marcel_core.channels.telegram.webhook.summarize_active_segment',
                new_callable=AsyncMock,
                side_effect=RuntimeError('oops'),
            ),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_bot.send_message = AsyncMock()
            await _run_forget(123, 'alice')
        # Should have sent an error message
        mock_bot.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


class TestWebhookEndpoint:
    def test_missing_secret_returns_503(self, client):
        with patch('marcel_core.channels.telegram.webhook.settings') as mock_settings:
            mock_settings.telegram_webhook_secret = ''
            resp = client.post('/telegram/webhook', json={})
        assert resp.status_code == 503

    def test_invalid_secret_returns_403(self, client):
        with patch('marcel_core.channels.telegram.webhook.settings') as mock_settings:
            mock_settings.telegram_webhook_secret = 'correct'
            resp = client.post(
                '/telegram/webhook',
                json={},
                headers={'x-telegram-bot-api-secret-token': 'wrong'},
            )
        assert resp.status_code == 403

    def test_no_message_ignored(self, client):
        with patch('marcel_core.channels.telegram.webhook.settings') as mock_settings:
            mock_settings.telegram_webhook_secret = 'secret'
            resp = client.post(
                '/telegram/webhook',
                json={'update_id': 1},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ignored'

    def test_empty_text_ignored(self, client):
        with patch('marcel_core.channels.telegram.webhook.settings') as mock_settings:
            mock_settings.telegram_webhook_secret = 'secret'
            resp = client.post(
                '/telegram/webhook',
                json={'message': {'chat': {'id': 123}, 'text': ''}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ignored'

    def test_start_command(self, client):
        with (
            patch('marcel_core.channels.telegram.webhook.settings') as mock_settings,
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_settings.telegram_webhook_secret = 'secret'
            mock_bot.send_message = AsyncMock()
            resp = client.post(
                '/telegram/webhook',
                json={'message': {'chat': {'id': 123}, 'text': '/start'}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ok'

    def test_unlinked_user(self, client):
        with (
            patch('marcel_core.channels.telegram.webhook.settings') as mock_settings,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_settings.telegram_webhook_secret = 'secret'
            mock_sessions.get_user_slug.return_value = None
            mock_bot.send_message = AsyncMock()
            resp = client.post(
                '/telegram/webhook',
                json={'message': {'chat': {'id': 999}, 'text': 'Hello'}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ok'

    def test_forget_command(self, client):
        with (
            patch('marcel_core.channels.telegram.webhook.settings') as mock_settings,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook.has_active_content', return_value=False),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_settings.telegram_webhook_secret = 'secret'
            mock_sessions.get_user_slug.return_value = 'alice'
            mock_bot.send_message = AsyncMock()
            resp = client.post(
                '/telegram/webhook',
                json={'message': {'chat': {'id': 123}, 'text': '/forget'}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.status_code == 200

    def test_callback_query(self, client):
        with (
            patch('marcel_core.channels.telegram.webhook.settings') as mock_settings,
            patch('marcel_core.channels.telegram.webhook._handle_callback_query', new_callable=AsyncMock),
        ):
            mock_settings.telegram_webhook_secret = 'secret'
            resp = client.post(
                '/telegram/webhook',
                json={'callback_query': {'id': 'q1', 'data': 'cal:conv:0'}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ok'

    def test_new_command(self, client):
        """The /new command is an alias for /forget."""
        with (
            patch('marcel_core.channels.telegram.webhook.settings') as mock_settings,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook.has_active_content', return_value=True),
            patch('marcel_core.channels.telegram.webhook._run_forget', new_callable=AsyncMock),
        ):
            mock_settings.telegram_webhook_secret = 'secret'
            mock_sessions.get_user_slug.return_value = 'alice'
            resp = client.post(
                '/telegram/webhook',
                json={'message': {'chat': {'id': 123}, 'text': '/new'}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.json()['status'] == 'ok'

    def test_edited_message(self, client):
        """edited_message should be treated like a regular message."""
        with (
            patch('marcel_core.channels.telegram.webhook.settings') as mock_settings,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook._process_with_delayed_ack', new_callable=AsyncMock),
        ):
            mock_settings.telegram_webhook_secret = 'secret'
            mock_sessions.get_user_slug.return_value = 'alice'
            mock_sessions.touch_last_message = MagicMock()
            resp = client.post(
                '/telegram/webhook',
                json={'edited_message': {'chat': {'id': 123}, 'text': 'Updated text'}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.json()['status'] == 'ok'

    def test_regular_message_dispatches(self, client):
        with (
            patch('marcel_core.channels.telegram.webhook.settings') as mock_settings,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook._process_with_delayed_ack', new_callable=AsyncMock),
        ):
            mock_settings.telegram_webhook_secret = 'secret'
            mock_sessions.get_user_slug.return_value = 'alice'
            mock_sessions.touch_last_message = MagicMock()
            resp = client.post(
                '/telegram/webhook',
                json={'message': {'chat': {'id': 123}, 'text': 'What is the weather?'}},
                headers={'x-telegram-bot-api-secret-token': 'secret'},
            )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ok'


# ---------------------------------------------------------------------------
# _process_with_delayed_ack
# ---------------------------------------------------------------------------


class TestProcessWithDelayedAck:
    @pytest.mark.asyncio
    async def test_normal_processing(self):
        with (
            patch(
                'marcel_core.channels.telegram.webhook._process_assistant_message',
                new_callable=AsyncMock,
            ),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_bot.send_message = AsyncMock()
            await _process_with_delayed_ack(123, 'alice', 'Hello')

    @pytest.mark.asyncio
    async def test_exception_sends_error_reply(self):
        with (
            patch(
                'marcel_core.channels.telegram.webhook._process_assistant_message',
                new_callable=AsyncMock,
                side_effect=RuntimeError('agent crash'),
            ),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_bot.send_message = AsyncMock()
            await _process_with_delayed_ack(123, 'alice', 'Hello')
        # Should have tried to send an error message
        mock_bot.send_message.assert_called()


# ---------------------------------------------------------------------------
# _process_assistant_message
# ---------------------------------------------------------------------------


class TestProcessAssistantMessage:
    @pytest.mark.asyncio
    async def test_empty_response(self):
        with (
            patch('marcel_core.channels.telegram.webhook.stream_turn', return_value=self._empty_stream()),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_bot.send_message = AsyncMock()
            mock_bot.has_rich_content.return_value = False
            ack: dict = {'message_id': None, 'sent': False, 'cancelled': False}
            await _process_assistant_message(123, 'alice', 'test', ack)
        # Should notify about empty response
        assert mock_bot.send_message.called

    @pytest.mark.asyncio
    async def test_normal_response(self):
        from marcel_core.harness.runner import TextDelta

        async def _stream(*a, **kw):
            yield TextDelta(text='Hello world')

        with (
            patch('marcel_core.channels.telegram.webhook.stream_turn', side_effect=_stream),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.extract_and_save_memories'),
            patch('marcel_core.channels.telegram.webhook._format_response', return_value=('Hello world', None)),
        ):
            mock_bot.send_message = AsyncMock()
            mock_bot.has_rich_content.return_value = False
            ack: dict = {'message_id': None, 'sent': False, 'cancelled': False}
            await _process_assistant_message(123, 'alice', 'test', ack)
        mock_bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_edits_ack_message(self):
        from marcel_core.harness.runner import TextDelta

        async def _stream(*a, **kw):
            yield TextDelta(text='Response')

        with (
            patch('marcel_core.channels.telegram.webhook.stream_turn', side_effect=_stream),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.extract_and_save_memories'),
            patch('marcel_core.channels.telegram.webhook._format_response', return_value=('Response', None)),
        ):
            mock_bot.edit_message_text = AsyncMock()
            mock_bot.send_message = AsyncMock()
            mock_bot.has_rich_content.return_value = False
            ack: dict = {'message_id': 42, 'sent': True, 'cancelled': False}
            await _process_assistant_message(123, 'alice', 'test', ack)
        mock_bot.edit_message_text.assert_called()

    @pytest.mark.asyncio
    async def test_rich_content_creates_artifact(self):
        from marcel_core.harness.runner import TextDelta

        async def _stream(*a, **kw):
            yield TextDelta(text='- [ ] Task 1\n- [x] Task 2')

        with (
            patch('marcel_core.channels.telegram.webhook.stream_turn', side_effect=_stream),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.extract_and_save_memories'),
            patch('marcel_core.channels.telegram.webhook.create_artifact', return_value='art-1'),
            patch('marcel_core.channels.telegram.webhook._format_response', return_value=('html', None)),
        ):
            mock_bot.send_message = AsyncMock()
            mock_bot.has_rich_content.return_value = True
            mock_bot.detect_content_type.return_value = 'checklist'
            mock_bot.extract_title.return_value = 'Task List'
            ack: dict = {'message_id': None, 'sent': False, 'cancelled': False}
            await _process_assistant_message(123, 'alice', 'test', ack)

    @pytest.mark.asyncio
    async def test_timeout_with_partial(self):
        import asyncio

        from marcel_core.harness.runner import TextDelta

        async def _slow_stream(*a, **kw):
            yield TextDelta(text='Partial response')
            await asyncio.sleep(999)

        with (
            patch('marcel_core.channels.telegram.webhook.stream_turn', side_effect=_slow_stream),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook._ASSISTANT_TIMEOUT', 0.01),
        ):
            mock_bot.send_message = AsyncMock()
            ack: dict = {'message_id': None, 'sent': False, 'cancelled': False}
            await _process_assistant_message(123, 'alice', 'test', ack)
        # Should have sent partial response with timeout notice
        assert mock_bot.send_message.called

    @pytest.mark.asyncio
    async def test_exception_with_partial(self):
        from marcel_core.harness.runner import TextDelta

        call_count = 0

        async def _fail_stream(*a, **kw):
            nonlocal call_count
            call_count += 1
            yield TextDelta(text='Partial')
            raise RuntimeError('stream died')

        with (
            patch('marcel_core.channels.telegram.webhook.stream_turn', side_effect=_fail_stream),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
        ):
            mock_bot.send_message = AsyncMock()
            ack: dict = {'message_id': None, 'sent': False, 'cancelled': False}
            await _process_assistant_message(123, 'alice', 'test', ack)
        assert mock_bot.send_message.called

    @pytest.mark.asyncio
    async def test_send_failure_fallback(self):
        from marcel_core.harness.runner import TextDelta

        async def _stream(*a, **kw):
            yield TextDelta(text='Good response')

        with (
            patch('marcel_core.channels.telegram.webhook.stream_turn', side_effect=_stream),
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.extract_and_save_memories'),
            patch('marcel_core.channels.telegram.webhook._format_response', return_value=('html', None)),
        ):
            # First call (send_message) raises, second (error reply) succeeds
            mock_bot.send_message = AsyncMock(side_effect=[RuntimeError('send failed'), MagicMock()])
            mock_bot.has_rich_content.return_value = False
            ack: dict = {'message_id': None, 'sent': False, 'cancelled': False}
            await _process_assistant_message(123, 'alice', 'test', ack)

    @staticmethod
    async def _empty_stream(*a, **kw):
        return
        yield  # noqa: unreachable — makes this an async generator


# ---------------------------------------------------------------------------
# Callback query handler
# ---------------------------------------------------------------------------


class TestCallbackQueryHandler:
    @pytest.mark.asyncio
    async def test_non_calendar_callback_dismissed(self):
        with patch('marcel_core.channels.telegram.webhook.bot') as mock_bot:
            mock_bot.answer_callback_query = AsyncMock()
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'other:data',
                    'message': {'chat': {'id': 123}, 'message_id': 1},
                }
            )
        mock_bot.answer_callback_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_data_format_dismissed(self):
        with patch('marcel_core.channels.telegram.webhook.bot') as mock_bot:
            mock_bot.answer_callback_query = AsyncMock()
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'cal:only_two',
                    'message': {'chat': {'id': 123}, 'message_id': 1},
                }
            )
        mock_bot.answer_callback_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_page_number(self):
        with patch('marcel_core.channels.telegram.webhook.bot') as mock_bot:
            mock_bot.answer_callback_query = AsyncMock()
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'cal:conv-1:abc',
                    'message': {'chat': {'id': 123}, 'message_id': 1},
                }
            )
        mock_bot.answer_callback_query.assert_called_with('q1', 'Invalid page')

    @pytest.mark.asyncio
    async def test_no_user_slug(self):
        with (
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
        ):
            mock_bot.answer_callback_query = AsyncMock()
            mock_sessions.get_user_slug.return_value = None
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'cal:conv-1:0',
                    'message': {'chat': {'id': 123}, 'message_id': 1},
                }
            )
        mock_bot.answer_callback_query.assert_called_with('q1', 'Session expired')

    @pytest.mark.asyncio
    async def test_no_assistant_messages(self):
        with (
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook.read_active_segment', return_value=[]),
        ):
            mock_bot.answer_callback_query = AsyncMock()
            mock_sessions.get_user_slug.return_value = 'alice'
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'cal:conv-1:0',
                    'message': {'chat': {'id': 123}, 'message_id': 1},
                }
            )
        mock_bot.answer_callback_query.assert_called_with('q1', 'Conversation not found')

    @pytest.mark.asyncio
    async def test_successful_page_navigation(self):
        from datetime import datetime, timezone

        from marcel_core.memory.history import HistoryMessage

        msg = HistoryMessage(
            role='assistant',
            text='calendar text',
            timestamp=datetime.now(timezone.utc),
            conversation_id='conv-1',
        )
        with (
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook.read_active_segment', return_value=[msg]),
            patch('marcel_core.channels.telegram.webhook.parse_day_groups', return_value=[MagicMock(), MagicMock()]),
            patch('marcel_core.channels.telegram.webhook.format_calendar_page', return_value='<b>Page</b>'),
            patch('marcel_core.channels.telegram.webhook.calendar_nav_markup', return_value={}),
        ):
            mock_bot.answer_callback_query = AsyncMock()
            mock_bot.edit_message_text = AsyncMock()
            mock_sessions.get_user_slug.return_value = 'alice'
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'cal:conv-1:0',
                    'message': {'chat': {'id': 123}, 'message_id': 1},
                }
            )
        mock_bot.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_day_groups(self):
        from datetime import datetime, timezone

        from marcel_core.memory.history import HistoryMessage

        msg = HistoryMessage(
            role='assistant',
            text='Just plain text',
            timestamp=datetime.now(timezone.utc),
            conversation_id='conv-1',
        )
        with (
            patch('marcel_core.channels.telegram.webhook.bot') as mock_bot,
            patch('marcel_core.channels.telegram.webhook.sessions') as mock_sessions,
            patch('marcel_core.channels.telegram.webhook.read_active_segment', return_value=[msg]),
            patch('marcel_core.channels.telegram.webhook.parse_day_groups', return_value=None),
        ):
            mock_bot.answer_callback_query = AsyncMock()
            mock_sessions.get_user_slug.return_value = 'alice'
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'cal:conv-1:0',
                    'message': {'chat': {'id': 123}, 'message_id': 1},
                }
            )
