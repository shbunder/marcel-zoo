"""Periodic transaction and balance sync for linked bank accounts.

Invoked by the declarative ``scheduled_jobs:`` entry in
``integration.yaml`` (ISSUE-82f52b). Stays within PSD2 rate limits
(4 requests/day without active SCA) by running every 8 hours.

Also monitors consent expiry and surfaces a warning when < 7 days remain.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from marcel_core.plugin import get_logger

from .cache import get_sync_meta, set_sync_meta, upsert_balances, upsert_transactions
from .client import get_all_transactions, get_balances, get_session, get_stored_sessions

log = get_logger(__name__)

_CONSENT_WARN_DAYS = 7


async def sync_account(slug: str) -> dict[str, Any]:
    """Run a single sync cycle for all the user's linked bank accounts.

    Iterates all stored EnableBanking sessions, fetches balances and
    recent transactions, and upserts them into the local SQLite cache.

    Returns a summary dict with counts and any warnings.
    """
    summary: dict[str, Any] = {'synced': 0, 'warnings': [], 'banks': []}

    sessions = get_stored_sessions(slug)
    if not sessions:
        summary['warnings'].append('No bank links found — run banking.setup first')
        return summary

    last_sync = get_sync_meta(slug, 'last_sync_date')
    if last_sync:
        date_from = last_sync
    else:
        date_from = (date.today() - timedelta(days=90)).isoformat()
    date_to = date.today().isoformat()

    for entry in sessions:
        bank_name = entry.get('bank', 'Unknown')
        session_id = entry.get('session_id', '')
        if not session_id:
            continue

        try:
            session = await get_session(slug, session_id)
        except Exception:
            summary['warnings'].append(f'{bank_name} session fetch failed')
            continue

        if session.get('status') != 'AUTHORIZED':
            summary['warnings'].append(
                f'{bank_name} session status is {session.get("status", "unknown")} — expected AUTHORIZED'
            )
            continue

        accounts = session.get('accounts', [])
        bank_synced = 0

        for account in accounts:
            account_uid = account if isinstance(account, str) else account.get('uid', '')
            if not account_uid:
                continue
            try:
                balances = await get_balances(slug, account_uid)
                upsert_balances(slug, account_uid, balances)

                txs = await get_all_transactions(
                    slug,
                    account_uid,
                    date_from=date_from,
                    date_to=date_to,
                )
                if txs:
                    upsert_transactions(slug, account_uid, txs)
                    bank_synced += len(txs)

            except Exception:
                log.exception('Failed to sync account %s (%s) for user %s', account_uid, bank_name, slug)
                summary['warnings'].append(f'Failed to sync {bank_name} account {account_uid}')

        summary['synced'] += bank_synced
        summary['banks'].append({'bank': bank_name, 'synced': bank_synced})

    set_sync_meta(slug, 'last_sync_date', date_to)
    set_sync_meta(slug, 'last_sync_at', datetime.now(UTC).isoformat())
    log.info('Bank sync complete for %s: %d transactions', slug, summary['synced'])
    return summary


async def check_consent_expiry(slug: str) -> list[str]:
    """Check if any bank consent is about to expire.

    Returns a list of warning messages for sessions expiring within
    ``_CONSENT_WARN_DAYS`` days.
    """
    warnings: list[str] = []
    for entry in get_stored_sessions(slug):
        bank_name = entry.get('bank', 'Unknown')
        session_id = entry.get('session_id', '')
        if not session_id:
            continue
        try:
            session = await get_session(slug, session_id)
        except Exception:
            continue

        access = session.get('access', {})
        valid_until_str = access.get('valid_until', '')
        if not valid_until_str:
            continue

        try:
            expires = datetime.fromisoformat(valid_until_str.replace('Z', '+00:00'))
            days_left = (expires - datetime.now(tz=expires.tzinfo)).days

            if days_left <= _CONSENT_WARN_DAYS:
                warnings.append(
                    f'Your {bank_name} bank link expires in {days_left} day{"s" if days_left != 1 else ""}. '
                    f'Ask Marcel to run "banking.setup" with bank="{bank_name}" to re-authenticate.'
                )
        except (ValueError, TypeError):
            log.warning('Could not parse session expiry for %s (%s)', slug, bank_name)

    return warnings
