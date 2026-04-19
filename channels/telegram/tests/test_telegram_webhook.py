"""Extended tests for channels/telegram/webhook.py — internal functions."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from marcel_core.channels.telegram import sessions
from marcel_core.channels.telegram.webhook import _format_response
from marcel_core.config import settings
from marcel_core.main import app
from marcel_core.storage import _root

_WEBHOOK_HEADERS = {'x-telegram-bot-api-secret-token': 'test-secret'}


def _make_update(chat_id: int, text: str) -> dict:
    return {
        'update_id': 1,
        'message': {
            'message_id': 100,
            'chat': {'id': chat_id, 'type': 'private'},
            'from': {'id': chat_id, 'first_name': 'Test', 'is_bot': False},
            'text': text,
            'date': 1700000000,
        },
    }


# ---------------------------------------------------------------------------
# _format_response — pure function tests
# ---------------------------------------------------------------------------


class TestFormatResponse:
    def test_plain_text_response(self):
        html, markup = _format_response('Hello there!', 'conv-1')
        assert isinstance(html, str)
        assert 'Hello' in html
        assert markup is None

    def test_rich_content_returns_html(self):
        # A markdown table triggers rich content detection
        md = '| Name | Score | Rank |\n|------|-------|------|\n| Alice | 10 | 1 |\n'
        html, markup = _format_response(md, 'conv-1')
        assert isinstance(html, str)
        # markup may be None if no public URL configured — just check html

    def test_calendar_response_single_page(self):
        # Calendar content: a few day headers
        calendar_text = '**Monday 1 April**\n- Event 1\n\n**Tuesday 2 April**\n- Event 2\n\n'
        html, markup = _format_response(calendar_text, 'conv-1')
        assert isinstance(html, str)

    def test_calendar_response_multi_page(self):
        # Create >7 days to trigger multi-page calendar
        days = ''.join(
            f'**{day} April**\n- Appointment {i + 1}\n\n'
            for i, day in enumerate(
                ['Monday 1', 'Tuesday 2', 'Wednesday 3', 'Thursday 4', 'Friday 5', 'Saturday 6', 'Sunday 7', 'Monday 8']
            )
        )
        html, markup = _format_response(days, 'conv-multi')
        assert isinstance(html, str)

    def test_artifact_id_embedded_in_markup(self, monkeypatch):
        monkeypatch.setattr(settings, 'marcel_public_url', 'https://example.com')
        md = '| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n'
        html, markup = _format_response(md, 'conv-1', artifact_id='art-123')
        if markup and 'inline_keyboard' in markup:
            buttons_text = json.dumps(markup)
            assert 'art-123' in buttons_text


# ---------------------------------------------------------------------------
# _process_assistant_message — timeout and empty response
# ---------------------------------------------------------------------------


class TestProcessAssistantMessage:
    @pytest.mark.asyncio
    async def test_timeout_sends_reply(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        from marcel_core.channels.telegram.webhook import _process_assistant_message

        async def slow_stream(*args, **kwargs):
            await asyncio.sleep(100)
            return
            yield  # make it a generator

        sent = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook.stream_turn', slow_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                with patch('marcel_core.channels.telegram.webhook._ASSISTANT_TIMEOUT', 0.01):
                    await _process_assistant_message(
                        42, 'shaun', 'hello', {'message_id': None, 'sent': False, 'cancelled': False}
                    )

        assert any('long' in t.lower() or 'took' in t.lower() or 'sorry' in t.lower() for t in sent)

    @pytest.mark.asyncio
    async def test_empty_response_sends_apology(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        from marcel_core.channels.telegram.webhook import _process_assistant_message

        async def empty_stream(*args, **kwargs):
            return
            yield  # generator

        sent = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook.stream_turn', empty_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                await _process_assistant_message(
                    42, 'shaun', 'hello', {'message_id': None, 'sent': False, 'cancelled': False}
                )

        assert any('empty' in t.lower() or 'sorry' in t.lower() for t in sent)

    @pytest.mark.asyncio
    async def test_stream_exception_sends_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        from marcel_core.channels.telegram.webhook import _process_assistant_message

        async def broken_stream(*args, **kwargs):
            raise RuntimeError('agent crash')
            yield

        sent = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook.stream_turn', broken_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                await _process_assistant_message(
                    42, 'shaun', 'hello', {'message_id': None, 'sent': False, 'cancelled': False}
                )

        assert any('wrong' in t.lower() or 'sorry' in t.lower() or 'error' in t.lower() for t in sent)

    @pytest.mark.asyncio
    async def test_ack_edit_when_ack_was_sent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        from marcel_core.channels.telegram.webhook import _process_assistant_message
        from marcel_core.harness.runner import TextDelta

        async def fast_stream(*args, **kwargs):
            yield TextDelta(text='Reply text')

        edited = []

        async def fake_edit(chat_id, message_id, text, **kwargs):
            edited.append((chat_id, message_id, text))

        with patch('marcel_core.channels.telegram.webhook.stream_turn', fast_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', AsyncMock(return_value=1)):
                with patch('marcel_core.channels.telegram.bot.edit_message_text', fake_edit):
                    with patch('marcel_core.channels.telegram.webhook.extract_and_save_memories', AsyncMock()):
                        await _process_assistant_message(
                            42, 'shaun', 'hello', {'message_id': 99, 'sent': True, 'cancelled': False}
                        )

        assert any(e[1] == 99 for e in edited)


# ---------------------------------------------------------------------------
# Slash-prefix wiring (ISSUE-6a38cd) — /fast, /power, /<skillname>
# ---------------------------------------------------------------------------


class TestTelegramSlashPrefixes:
    @pytest.mark.asyncio
    async def test_fast_prefix_strips_slash_and_sets_tier(self, tmp_path, monkeypatch):
        """``/fast hello`` → stream_turn receives cleaned text ``hello`` at tier FAST."""
        from marcel_core.channels.telegram.webhook import _process_assistant_message
        from marcel_core.harness.model_chain import Tier
        from marcel_core.harness.runner import TextDelta
        from marcel_core.harness.turn_router import TierSource

        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        captured: dict = {}

        async def fake_stream(user_slug, channel, user_text, conversation_id, **kwargs):
            captured['user_text'] = user_text
            captured['turn_plan'] = kwargs.get('turn_plan')
            yield TextDelta(text='ok')

        with patch('marcel_core.channels.telegram.webhook.stream_turn', fake_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', AsyncMock(return_value=1)):
                with patch('marcel_core.channels.telegram.webhook.extract_and_save_memories', AsyncMock()):
                    await _process_assistant_message(
                        42, 'shaun', '/fast hello', {'message_id': None, 'sent': False, 'cancelled': False}
                    )

        plan = captured['turn_plan']
        assert plan is not None
        assert plan.tier is Tier.FAST
        assert plan.source is TierSource.USER_PREFIX
        assert plan.cleaned_text == 'hello'

    @pytest.mark.asyncio
    async def test_power_prefix_is_rejected_without_model_call(self, tmp_path, monkeypatch):
        """``/power ...`` replies with the canned rejection and never enters stream_turn."""
        from marcel_core.channels.telegram.webhook import _process_assistant_message
        from marcel_core.harness.turn_router import POWER_REJECT_MESSAGE

        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        stream_called = False

        async def never_stream(*args, **kwargs):
            nonlocal stream_called
            stream_called = True
            yield

        sent: list[str] = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook.stream_turn', never_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                await _process_assistant_message(
                    42, 'shaun', '/power give me opus', {'message_id': None, 'sent': False, 'cancelled': False}
                )

        assert stream_called is False
        # POWER_REJECT_MESSAGE goes through escape_html for the send path.
        assert any('power' in t.lower() for t in sent)
        assert any('reserved' in t.lower() for t in sent)
        # Sanity check the message we built matches the canonical constant.
        assert 'power' in POWER_REJECT_MESSAGE.lower()

    @pytest.mark.asyncio
    async def test_skill_prefix_seeds_read_skills_and_passes_args(self, tmp_path, monkeypatch):
        """``/weather tomorrow`` → plan has skill_override='weather' and cleaned_text='tomorrow'."""
        from marcel_core.channels.telegram.webhook import _process_assistant_message
        from marcel_core.harness.runner import TextDelta
        from marcel_core.skills.loader import SkillDoc

        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        captured: dict = {}

        async def fake_stream(user_slug, channel, user_text, conversation_id, **kwargs):
            captured['user_text'] = user_text
            captured['turn_plan'] = kwargs.get('turn_plan')
            yield TextDelta(text='ok')

        weather_doc = SkillDoc(
            name='weather',
            description='',
            content='',
            is_setup=False,
            source='data',
            preferred_tier=None,
        )
        with patch('marcel_core.skills.loader.load_skills', return_value=[weather_doc]):
            with patch('marcel_core.channels.telegram.webhook.stream_turn', fake_stream):
                with patch('marcel_core.channels.telegram.bot.send_message', AsyncMock(return_value=1)):
                    with patch('marcel_core.channels.telegram.webhook.extract_and_save_memories', AsyncMock()):
                        await _process_assistant_message(
                            42,
                            'shaun',
                            '/weather tomorrow',
                            {'message_id': None, 'sent': False, 'cancelled': False},
                        )

        plan = captured['turn_plan']
        assert plan is not None
        assert plan.skill_override == 'weather'
        assert plan.cleaned_text == 'tomorrow'


# ---------------------------------------------------------------------------
# Callback query handling
# ---------------------------------------------------------------------------


class TestHandleCallbackQuery:
    @pytest.mark.asyncio
    async def test_non_cal_callback_answered(self):
        from marcel_core.channels.telegram.webhook import _handle_callback_query

        answered = []

        async def fake_answer(query_id, text=None):
            answered.append(query_id)

        with patch('marcel_core.channels.telegram.bot.answer_callback_query', fake_answer):
            await _handle_callback_query(
                {
                    'id': 'q1',
                    'data': 'other:data',
                    'message': {'chat': {'id': 42}, 'message_id': 1},
                }
            )

        assert 'q1' in answered

    @pytest.mark.asyncio
    async def test_malformed_cal_callback_answered(self):
        from marcel_core.channels.telegram.webhook import _handle_callback_query

        answered = []

        async def fake_answer(query_id, text=None):
            answered.append(query_id)

        with patch('marcel_core.channels.telegram.bot.answer_callback_query', fake_answer):
            await _handle_callback_query(
                {
                    'id': 'q2',
                    'data': 'cal:only_one_part',
                    'message': {'chat': {'id': 42}, 'message_id': 1},
                }
            )

        assert 'q2' in answered

    @pytest.mark.asyncio
    async def test_invalid_page_answered(self):
        from marcel_core.channels.telegram.webhook import _handle_callback_query

        answered = []

        async def fake_answer(query_id, text=None):
            answered.append((query_id, text))

        with patch('marcel_core.channels.telegram.bot.answer_callback_query', fake_answer):
            await _handle_callback_query(
                {
                    'id': 'q3',
                    'data': 'cal:conv-1:notanumber',
                    'message': {'chat': {'id': 42}, 'message_id': 1},
                }
            )

        assert any(qid == 'q3' for qid, _ in answered)

    @pytest.mark.asyncio
    async def test_unlinked_user_answered(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)

        from marcel_core.channels.telegram.webhook import _handle_callback_query

        answered = []

        async def fake_answer(query_id, text=None):
            answered.append((query_id, text))

        # No user linked to chat 42
        with patch('marcel_core.channels.telegram.bot.answer_callback_query', fake_answer):
            await _handle_callback_query(
                {
                    'id': 'q4',
                    'data': 'cal:conv-1:0',
                    'message': {'chat': {'id': 42}, 'message_id': 1},
                }
            )

        assert any(qid == 'q4' for qid, _ in answered)

    @pytest.mark.asyncio
    async def test_no_conversation_answered(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        sessions.link_user('shaun', 42)

        from marcel_core.channels.telegram.webhook import _handle_callback_query

        answered = []

        async def fake_answer(query_id, text=None):
            answered.append((query_id, text))

        with patch('marcel_core.channels.telegram.bot.answer_callback_query', fake_answer):
            await _handle_callback_query(
                {
                    'id': 'q5',
                    'data': 'cal:nonexistent-conv:0',
                    'message': {'chat': {'id': 42}, 'message_id': 1},
                }
            )

        assert any(qid == 'q5' for qid, _ in answered)


# ---------------------------------------------------------------------------
# Webhook endpoint — callback query dispatch
# ---------------------------------------------------------------------------


class TestWebhookCallbackQuery:
    @respx.mock
    def test_callback_query_returns_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')

        respx.post('https://api.telegram.org/bottest-token/answerCallbackQuery').mock(
            return_value=Response(200, json={'ok': True})
        )

        update = {
            'update_id': 1,
            'callback_query': {
                'id': 'cq-1',
                'data': 'other:data',
                'message': {
                    'message_id': 10,
                    'chat': {'id': 42, 'type': 'private'},
                },
            },
        }

        client = TestClient(app)
        resp = client.post('/telegram/webhook', json=update, headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok'}


# ---------------------------------------------------------------------------
# Continuous conversation — idle messages still dispatch normally
# ---------------------------------------------------------------------------


class TestContinuousConversation:
    @respx.mock
    def test_idle_chat_dispatches_normally(self, tmp_path, monkeypatch):
        """After a long idle period, the next message should still dispatch normally."""
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')
        sessions.link_user('shaun', 555)

        from datetime import datetime, timedelta, timezone

        from marcel_core.memory.conversation import ensure_channel, save_channel_meta

        meta = ensure_channel('shaun', 'telegram')
        meta.last_active = datetime.now(timezone.utc) - timedelta(hours=7)
        save_channel_meta('shaun', 'telegram', meta)

        from marcel_core.harness.runner import TextDelta

        async def fake_stream(*args, **kwargs):
            yield TextDelta(text='hi')

        with patch('marcel_core.channels.telegram.webhook.stream_turn', fake_stream):
            with patch('marcel_core.channels.telegram.webhook.extract_and_save_memories', AsyncMock()):
                respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
                    return_value=Response(200, json={'ok': True})
                )
                client = TestClient(app)
                resp = client.post('/telegram/webhook', json=_make_update(555, 'hello'), headers=_WEBHOOK_HEADERS)

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Local-tier warm-up (ISSUE-7985aa) — tier-aware ack text + timeout
# ---------------------------------------------------------------------------


class TestLocalWarmup:
    """The LOCAL tier gets a warm-up ack message and a wider timeout.

    Ollama cold-start on a 14B is 30–60s to first token plus ~3–5 tok/s
    generation — the 120s cloud budget is too tight and the generic
    "Working on it..." ack is misleading while the model is still loading.
    """

    def test_ack_text_for_local_is_warmup(self):
        from marcel_core.channels.telegram.webhook import _ACK_LOCAL_WARMUP, _ack_text_for
        from marcel_core.harness.model_chain import Tier
        from marcel_core.harness.turn_router import TierSource, TurnPlan

        plan = TurnPlan(tier=Tier.LOCAL, cleaned_text='hi', source=TierSource.USER_PREFIX)
        assert _ack_text_for(plan) == _ACK_LOCAL_WARMUP

    def test_ack_text_for_cloud_tiers_is_generic(self):
        from marcel_core.channels.telegram.webhook import _ACK_CLOUD, _ack_text_for
        from marcel_core.harness.model_chain import Tier
        from marcel_core.harness.turn_router import TierSource, TurnPlan

        for tier in (Tier.FAST, Tier.STANDARD, Tier.POWER):
            plan = TurnPlan(tier=tier, cleaned_text='hi', source=TierSource.USER_PREFIX)
            assert _ack_text_for(plan) == _ACK_CLOUD, f'cloud ack expected for {tier}'

    def test_timeout_for_local_reads_setting(self, monkeypatch):
        from marcel_core.channels.telegram.webhook import _timeout_for
        from marcel_core.harness.model_chain import Tier
        from marcel_core.harness.turn_router import TierSource, TurnPlan

        monkeypatch.setattr(settings, 'marcel_local_llm_timeout', 987.5)
        plan = TurnPlan(tier=Tier.LOCAL, cleaned_text='hi', source=TierSource.USER_PREFIX)
        assert _timeout_for(plan) == 987.5

    def test_timeout_for_cloud_tiers_uses_assistant_timeout(self):
        from marcel_core.channels.telegram.webhook import _ASSISTANT_TIMEOUT, _timeout_for
        from marcel_core.harness.model_chain import Tier
        from marcel_core.harness.turn_router import TierSource, TurnPlan

        for tier in (Tier.FAST, Tier.STANDARD, Tier.POWER):
            plan = TurnPlan(tier=tier, cleaned_text='hi', source=TierSource.USER_PREFIX)
            assert _timeout_for(plan) == _ASSISTANT_TIMEOUT, f'cloud timeout expected for {tier}'

    @pytest.mark.asyncio
    async def test_local_turn_honors_local_timeout(self, tmp_path, monkeypatch):
        """A ``/local`` turn uses ``marcel_local_llm_timeout`` — firing it proves the branch works."""
        from marcel_core.channels.telegram.webhook import _process_assistant_message
        from marcel_core.harness.runner import TextDelta

        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'marcel_local_llm_timeout', 0.01)
        # Set the cloud timeout high so a leaky branch would NOT time out,
        # making the test fail loudly if the local branch is bypassed.
        monkeypatch.setattr('marcel_core.channels.telegram.webhook._ASSISTANT_TIMEOUT', 100.0)

        async def slow_stream(*args, **kwargs):
            yield TextDelta(text='partial')
            await asyncio.sleep(5)

        sent: list[str] = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook.stream_turn', slow_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                await _process_assistant_message(
                    42, 'shaun', '/local hello', {'message_id': None, 'sent': False, 'cancelled': False}
                )

        assert any('took too long' in t or 'cut short' in t for t in sent), f'expected timeout reply, got: {sent!r}'

    @pytest.mark.asyncio
    async def test_cloud_turn_still_uses_assistant_timeout(self, tmp_path, monkeypatch):
        """``/fast`` turns keep the tighter cloud budget unchanged."""
        from marcel_core.channels.telegram.webhook import _process_assistant_message
        from marcel_core.harness.runner import TextDelta

        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        # If the local branch is accidentally reached, this generous value
        # would prevent the timeout from firing within the test budget.
        monkeypatch.setattr(settings, 'marcel_local_llm_timeout', 100.0)
        monkeypatch.setattr('marcel_core.channels.telegram.webhook._ASSISTANT_TIMEOUT', 0.01)

        async def slow_stream(*args, **kwargs):
            yield TextDelta(text='partial')
            await asyncio.sleep(5)

        sent: list[str] = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook.stream_turn', slow_stream):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                await _process_assistant_message(
                    42, 'shaun', '/fast hello', {'message_id': None, 'sent': False, 'cancelled': False}
                )

        assert any('took too long' in t or 'cut short' in t for t in sent), f'expected timeout reply, got: {sent!r}'

    @pytest.mark.asyncio
    async def test_delayed_ack_uses_warmup_text_for_local(self, tmp_path, monkeypatch):
        """When ``/local`` fires the delayed ack, the warm-up text is sent."""
        from marcel_core.channels.telegram.webhook import _ACK_LOCAL_WARMUP, _process_with_delayed_ack

        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        # Fire the ack almost immediately; keep processing slow so the ack
        # lands before completion.
        monkeypatch.setattr('marcel_core.channels.telegram.webhook._ACK_DELAY', 0.01)

        async def slow_process(*args, **kwargs):
            await asyncio.sleep(0.1)

        sent: list[str] = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook._process_assistant_message', slow_process):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                await _process_with_delayed_ack(42, 'shaun', '/local hello')

        # The ack goes through escape_html, and the warm-up text contains only
        # ASCII characters plus an em-dash, so it survives unchanged.
        assert any(_ACK_LOCAL_WARMUP in t for t in sent), f'expected warmup ack, got: {sent!r}'

    @pytest.mark.asyncio
    async def test_delayed_ack_uses_cloud_text_for_non_local(self, tmp_path, monkeypatch):
        """Non-local turns keep the generic ``Working on it...`` ack."""
        from marcel_core.channels.telegram.webhook import _ACK_CLOUD, _process_with_delayed_ack

        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr('marcel_core.channels.telegram.webhook._ACK_DELAY', 0.01)

        async def slow_process(*args, **kwargs):
            await asyncio.sleep(0.1)

        sent: list[str] = []

        async def fake_send(chat_id, text, **kwargs):
            sent.append(text)
            return 1

        with patch('marcel_core.channels.telegram.webhook._process_assistant_message', slow_process):
            with patch('marcel_core.channels.telegram.bot.send_message', fake_send):
                await _process_with_delayed_ack(42, 'shaun', '/fast hello')

        assert any(_ACK_CLOUD in t for t in sent), f'expected cloud ack, got: {sent!r}'
