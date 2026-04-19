"""Telegram webhook endpoint.

Receives updates from the Telegram Bot API and routes them through the
Marcel agent loop. Responds to each message after streaming completes.

Commands:
    /start  — show chat ID for account linking
    /forget — compress recent conversation into a summary
    /new    — alias for /forget (backward compatibility)

Webhook URL: POST /telegram/webhook
"""

import asyncio
import logging
import math
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from . import bot, sessions
from .formatting import (
    DAYS_PER_PAGE,
    calendar_nav_markup,
    escape_html,
    format_calendar_page,
    markdown_to_telegram_html,
    parse_day_groups,
    web_app_url_for,
)
from marcel_core.config import settings
from marcel_core.harness.model_chain import Tier
from marcel_core.harness.runner import TextDelta, stream_turn
from marcel_core.harness.turn_router import TurnPlan, resolve_turn_for_user
from marcel_core.memory import extract_and_save_memories
from marcel_core.memory.conversation import has_active_content, read_active_segment
from marcel_core.memory.summarizer import summarize_active_segment
from marcel_core.storage.artifacts import create_artifact

log = logging.getLogger(__name__)

router = APIRouter()

_ASSISTANT_TIMEOUT = 120.0

# Delay before showing "Working on it..." acknowledgment (seconds).
_ACK_DELAY = 10.0

# Ack text shown when the delayed-ack fires. Local tier gets a warm-up
# variant because Ollama cold-start on a 14B is 30–60s to first token plus
# ~3–5 tok/s generation on CPU — the generic "Working on it..." is
# misleading when the user just typed ``/local`` and nothing will stream
# for most of a minute.
_ACK_CLOUD = 'Working on it...'
_ACK_LOCAL_WARMUP = 'Warming up the local model — this can take a minute...'


def _ack_text_for(turn_plan: TurnPlan) -> str:
    """Pick the delayed-ack text based on the resolved tier."""
    return _ACK_LOCAL_WARMUP if turn_plan.tier == Tier.LOCAL else _ACK_CLOUD


def _timeout_for(turn_plan: TurnPlan) -> float:
    """Pick the per-turn wall-clock budget based on the resolved tier.

    LOCAL turns use ``settings.marcel_local_llm_timeout`` (default 300s) to
    accommodate Ollama cold-start. Cloud tiers keep the tighter
    ``_ASSISTANT_TIMEOUT`` so a genuinely hung cloud turn still fails fast.
    """
    if turn_plan.tier == Tier.LOCAL:
        return settings.marcel_local_llm_timeout
    return _ASSISTANT_TIMEOUT


async def _reply(chat_id: int, text: str) -> int | None:
    """Send a plain notification message, escaping for HTML."""
    return await bot.send_message(chat_id, escape_html(text))


# ---------------------------------------------------------------------------
# Assistant path
# ---------------------------------------------------------------------------


async def _process_with_delayed_ack(chat_id: int, user_slug: str, text: str) -> None:
    """Run assistant processing with a delayed acknowledgment.

    Resolves the turn plan up front so the ack text and per-turn timeout
    can both branch on the target tier. If processing takes longer than
    ``_ACK_DELAY`` seconds, sends a tier-appropriate ack (warm-up message
    for LOCAL, generic "Working on it..." otherwise) and later edits it
    with the final response.
    """
    ack: dict[str, Any] = {'message_id': None, 'sent': False, 'cancelled': False}

    turn_plan = resolve_turn_for_user(user_slug, text)
    ack_text = _ack_text_for(turn_plan)

    async def _send_delayed_ack() -> None:
        await asyncio.sleep(_ACK_DELAY)
        if not ack['cancelled']:
            msg_id = await bot.send_message(chat_id, escape_html(ack_text))
            ack['message_id'] = msg_id
            ack['sent'] = True

    ack_task = asyncio.create_task(_send_delayed_ack())

    try:
        await _process_assistant_message(chat_id, user_slug, text, ack, turn_plan=turn_plan)
    except Exception as exc:
        log.exception('%s-telegram: unhandled error processing message', user_slug)
        try:
            await _reply(chat_id, f'Sorry, an unexpected error occurred: {exc}')
        except Exception:
            log.exception('%s-telegram: also failed to send error reply', user_slug)
    finally:
        ack['cancelled'] = True
        ack_task.cancel()


async def _run_forget(chat_id: int, user_slug: str) -> None:
    """Run /forget: summarize the active segment and notify the user."""
    try:
        success = await summarize_active_segment(user_slug, 'telegram', trigger='manual')
        if success:
            await _reply(chat_id, "Got it — I've compressed our recent conversation. I'll remember the key points.")
        else:
            await _reply(chat_id, 'Compression failed — please try again later.')
    except Exception:
        log.exception('%s-telegram: /forget failed', user_slug)
        await _reply(chat_id, 'Something went wrong while compressing the conversation.')


async def _process_assistant_message(
    chat_id: int,
    user_slug: str,
    text: str,
    ack: dict[str, Any],
    *,
    turn_plan: TurnPlan | None = None,
) -> None:
    """Run the assistant agent for one message.

    ``turn_plan`` may be pre-resolved by the caller (so the delayed-ack
    path can pick a tier-appropriate message). When omitted, the plan is
    resolved here — preserves the test-harness entry point that calls this
    function directly.
    """
    # Continuous conversation: use a stable conversation ID per channel
    conversation_id = f'telegram-{chat_id}'

    # Parse slash prefixes (/fast, /power, /<skillname>) before any model work.
    # ``/power`` is rejected here — the reject text is sent as a normal reply
    # and the turn ends (no model call, no history change).
    if turn_plan is None:
        turn_plan = resolve_turn_for_user(user_slug, text)
    if turn_plan.reject_reason is not None:
        ack['cancelled'] = True
        if ack.get('sent') and ack.get('message_id'):
            try:
                await bot.edit_message_text(chat_id, ack['message_id'], escape_html(turn_plan.reject_reason))
            except Exception:
                await _reply(chat_id, turn_plan.reject_reason)
        else:
            await _reply(chat_id, turn_plan.reject_reason)
        return

    response_parts: list[str] = []
    try:

        async def _collect() -> None:
            async for event in stream_turn(user_slug, 'telegram', text, conversation_id, turn_plan=turn_plan):
                if isinstance(event, TextDelta):
                    response_parts.append(event.text)

        await asyncio.wait_for(_collect(), timeout=_timeout_for(turn_plan))
    except asyncio.TimeoutError:
        partial = ''.join(response_parts).strip()
        if partial:
            await _reply(chat_id, partial + '\n\n(response cut short — took too long)')
        else:
            await _reply(chat_id, 'Sorry, that took too long and I had to give up. Please try again.')
        return
    except Exception as exc:
        log.exception('%s-telegram: error processing message', user_slug)
        partial = ''.join(response_parts).strip()
        if partial:
            await _reply(chat_id, partial + '\n\n(response may be incomplete due to an error)')
        else:
            await _reply(chat_id, f'Sorry, something went wrong: {exc}')
        return

    full_response = ''.join(response_parts)

    if not full_response.strip():
        await _reply(
            chat_id,
            'Sorry, I received your message but produced an empty response. Please try again or rephrase your question.',
        )
        return

    asyncio.create_task(extract_and_save_memories(user_slug, turn_plan.cleaned_text, full_response, conversation_id))

    # Create an artifact if the response has rich content
    artifact_id: str | None = None
    try:
        if bot.has_rich_content(full_response):
            from marcel_core.storage.artifacts import ContentType

            content_type: ContentType = bot.detect_content_type(full_response)  # type: ignore[assignment]
            title = bot.extract_title(full_response)
            artifact_id = create_artifact(user_slug, conversation_id, content_type, full_response, title)
    except Exception:
        log.exception('%s-telegram: failed to create artifact', user_slug)

    # --- Format and send ---
    try:
        html_text, markup = _format_response(full_response, conversation_id, artifact_id=artifact_id)

        if ack.get('sent') and ack.get('message_id'):
            await bot.edit_message_text(chat_id, ack['message_id'], html_text, reply_markup=markup)
        else:
            await bot.send_message(chat_id, html_text, reply_markup=markup)
    except Exception as exc:
        await _reply(chat_id, f'I have a response but failed to send it: {exc}')


def _format_response(
    full_response: str,
    conversation_id: str,
    *,
    artifact_id: str | None = None,
) -> tuple[str, dict | None]:
    """Convert a raw markdown response to HTML and build appropriate markup.

    Args:
        full_response: The raw markdown response text.
        conversation_id: The conversation filename stem.
        artifact_id: If set, the "View in app" button links to this artifact.

    Returns:
        A ``(html_text, reply_markup)`` tuple.
    """
    has_rich = bot.has_rich_content(full_response)
    show_button = bot.needs_mini_app(full_response) and artifact_id is not None

    # Build the "View in app" markup — only for genuinely interactive content
    def _view_markup() -> dict | None:
        if show_button and artifact_id:
            return bot.artifact_markup(artifact_id)
        return None

    # Try calendar pagination if the response has calendar-like content
    day_groups = parse_day_groups(full_response) if has_rich else None

    if day_groups and len(day_groups) > DAYS_PER_PAGE:
        # Multi-page calendar with navigation buttons (no "View in app")
        html_text = format_calendar_page(day_groups, page=0)
        total_pages = math.ceil(len(day_groups) / DAYS_PER_PAGE)
        markup = calendar_nav_markup(
            conversation_id,
            page=0,
            total_pages=total_pages,
            web_app_url=web_app_url_for(conversation_id, artifact_id=artifact_id) if show_button else None,
        )
    elif day_groups:
        # Single-page calendar — expandable blockquotes, no button
        html_text = format_calendar_page(day_groups, page=0)
        markup = None
    else:
        # Regular message — convert markdown to HTML
        html_text = markdown_to_telegram_html(full_response)
        markup = _view_markup()

    return html_text, markup


# ---------------------------------------------------------------------------
# Callback query handler (calendar navigation)
# ---------------------------------------------------------------------------


async def _handle_callback_query(callback_query: dict[str, Any]) -> None:
    """Handle inline keyboard button presses for calendar navigation."""
    query_id = callback_query['id']
    data = callback_query.get('data', '')
    message = callback_query.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    message_id = message.get('message_id')

    # Only handle calendar navigation callbacks
    if not data.startswith('cal:') or not chat_id or not message_id:
        await bot.answer_callback_query(query_id)
        return

    parts = data.split(':')
    if len(parts) != 3:
        await bot.answer_callback_query(query_id)
        return

    _, conversation_id, page_str = parts

    try:
        page = int(page_str)
    except ValueError:
        await bot.answer_callback_query(query_id, 'Invalid page')
        return

    user_slug = sessions.get_user_slug(chat_id)
    if not user_slug:
        await bot.answer_callback_query(query_id, 'Session expired')
        return

    # Load last assistant message from conversation segments
    messages = read_active_segment(user_slug, 'telegram')
    assistant_msgs = [m for m in messages if m.role == 'assistant' and m.text]
    if not assistant_msgs:
        await bot.answer_callback_query(query_id, 'Conversation not found')
        return

    assistant_text = assistant_msgs[-1].text
    if not assistant_text:
        await bot.answer_callback_query(query_id, 'Message not found')
        return

    day_groups = parse_day_groups(assistant_text)
    if not day_groups:
        await bot.answer_callback_query(query_id, 'No calendar data')
        return

    total_pages = math.ceil(len(day_groups) / DAYS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    html_text = format_calendar_page(day_groups, page)
    markup = calendar_nav_markup(
        conversation_id,
        page,
        total_pages,
        web_app_url=web_app_url_for(conversation_id),
    )

    await bot.edit_message_text(chat_id, message_id, html_text, reply_markup=markup)
    await bot.answer_callback_query(query_id)


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


@router.post('/telegram/webhook')
async def telegram_webhook(request: Request) -> dict[str, str]:
    """Receive an incoming update from the Telegram Bot API.

    Validates the optional webhook secret header, parses the update, and
    dispatches message handling as a background task so Telegram's 5-second
    timeout is not exceeded.

    Returns:
        ``{"status": "ok"}`` for handled updates, ``{"status": "ignored"}``
        for updates without an actionable message.
    """
    secret = settings.telegram_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail='TELEGRAM_WEBHOOK_SECRET is not configured')
    token_header = request.headers.get('x-telegram-bot-api-secret-token', '')
    if token_header != secret:
        raise HTTPException(status_code=403, detail='Invalid webhook secret')

    update: dict[str, Any] = await request.json()

    # --- Handle callback queries (inline button presses) ---
    callback_query = update.get('callback_query')
    if callback_query:
        asyncio.create_task(_handle_callback_query(callback_query))
        return {'status': 'ok'}

    message: dict[str, Any] | None = update.get('message') or update.get('edited_message')
    if not message:
        return {'status': 'ignored'}

    chat_id: int = message['chat']['id']
    text: str = message.get('text', '').strip()

    if not text:
        return {'status': 'ignored'}

    # --- /start: show chat ID for account linking ---
    if text == '/start':
        escaped_id = escape_html(str(chat_id))
        await bot.send_message(
            chat_id,
            f'Hi! Your Telegram chat ID is <code>{escaped_id}</code>.\n\n'
            f'Share this with your Marcel admin to link your account.',
        )
        return {'status': 'ok'}

    user_slug = sessions.get_user_slug(chat_id)
    if user_slug is None:
        escaped_id = escape_html(str(chat_id))
        await bot.send_message(
            chat_id,
            f'This chat is not linked to a Marcel user.\n\n'
            f'Your chat ID is <code>{escaped_id}</code>. Ask your admin to add it to <code>TELEGRAM_USER_MAP</code>.',
        )
        return {'status': 'ok'}

    # --- /forget or /new: compress conversation and start fresh segment ---
    if text in ('/forget', '/new'):
        if has_active_content(user_slug, 'telegram'):
            asyncio.create_task(_run_forget(chat_id, user_slug))
        else:
            await _reply(chat_id, 'Nothing to compress — the conversation is already fresh.')
        return {'status': 'ok'}

    # Update last-message timestamp
    sessions.touch_last_message(chat_id)

    # --- Dispatch to assistant (with delayed ack) ---
    log.info('%s-telegram: incoming message: %r', user_slug, text[:80])
    asyncio.create_task(_process_with_delayed_ack(chat_id, user_slug, text))

    return {'status': 'ok'}
