"""Banking integration — account, balance, and transaction access.

Registers ``banking.setup``, ``banking.complete_setup``, ``banking.accounts``,
``banking.balance``, ``banking.transactions``, ``banking.status``, and
``banking.sync`` as plugin integration handlers, callable through the
``integration`` tool.

Supports multiple banks (KBC, ING, etc.) via EnableBanking. Data is served
from a local SQLite cache at ``<cache_dir>/banking.db`` (resolved via
:mod:`marcel_core.plugin.paths`) that syncs every 8 hours via the declarative
``scheduled_jobs:`` entry in :file:`integration.yaml`.

System-scope fan-out: when ``banking.sync`` is invoked with
``user_slug='_system'`` (the scheduler's dispatch for habitat jobs), the
handler iterates every live user slug on disk and syncs each user that has
EnableBanking credentials. When called directly with a real slug (via the
``integration`` tool), it syncs just that user.
"""

from __future__ import annotations

import json
import re

from marcel_core.plugin import credentials, get_logger, paths, register

from .cache import get_balances, get_sync_meta, get_transactions, upsert_balances
from .client import (
    SUPPORTED_BANKS,
    create_session,
    get_session,
    get_stored_sessions,
    list_accounts,
    start_authorization,
)
from .client import get_balances as client_get_balances
from .sync import sync_account

log = get_logger(__name__)

_SYSTEM_USER = '_system'
_BACKUP_SLUG_RE = re.compile(r'\.backup-\d')


def _live_user_slugs() -> list[str]:
    """Return the slugs the sync job should touch — every on-disk user minus
    backup snapshots and the ``_system`` sentinel itself.
    """
    return sorted(
        slug for slug in paths.list_user_slugs() if slug != _SYSTEM_USER and not _BACKUP_SLUG_RE.search(slug)
    )


def _has_banking_creds(slug: str) -> bool:
    creds = credentials.load(slug)
    return bool(
        creds.get('ENABLEBANKING_APP_ID')
        and (creds.get('ENABLEBANKING_SESSIONS') or creds.get('ENABLEBANKING_SESSION_ID'))
    )


@register('banking.setup')
async def setup(params: dict, user_slug: str) -> str:
    """Start a bank link flow via EnableBanking.

    Returns the authentication URL the user must open to authorize access.
    """
    bank = params.get('bank', 'KBC').upper()
    country = params.get('country', SUPPORTED_BANKS.get(bank, {}).get('country', 'BE'))
    redirect = params.get('redirect_url', 'https://enablebanking.com')
    data = await start_authorization(
        user_slug,
        redirect_url=redirect,
        bank=bank,
        country=country,
    )
    return json.dumps(
        {
            'status': 'authorization_started',
            'bank': bank,
            'auth_url': data.get('url', ''),
            'instructions': (
                f'Open the auth_url in your browser to link your {bank} account. '
                f'After authenticating, you will be redirected. '
                f'Copy the full redirect URL and provide it to complete setup '
                f'using banking.complete_setup with bank="{bank}".'
            ),
        },
        indent=2,
    )


@register('banking.complete_setup')
async def complete_setup(params: dict, user_slug: str) -> str:
    """Complete the bank link by exchanging the authorization code for a session.

    The code is extracted from the redirect URL query parameter.
    """
    code = params.get('code', '')
    if not code:
        return json.dumps({'error': 'code parameter is required — extract it from the redirect URL'})

    bank = params.get('bank', 'KBC').upper()
    country = params.get('country', SUPPORTED_BANKS.get(bank, {}).get('country', 'BE'))
    session = await create_session(user_slug, code, bank=bank, country=country)
    accounts = session.get('accounts', [])
    return json.dumps(
        {
            'status': 'linked',
            'bank': bank,
            'session_id': session.get('session_id', ''),
            'accounts': len(accounts),
            'message': f'Successfully linked {len(accounts)} {bank} account(s). Running initial sync...',
        },
        indent=2,
    )


@register('banking.status')
async def status(params: dict, user_slug: str) -> str:
    """Check the status of all linked bank sessions."""
    sessions = get_stored_sessions(user_slug)
    if not sessions:
        return json.dumps({'error': 'No bank links found. Run banking.setup to link a bank account.'})

    results: list[dict] = []
    for entry in sessions:
        bank_name = entry.get('bank', 'Unknown')
        session_id = entry.get('session_id', '')
        try:
            session = await get_session(user_slug, session_id)
            result: dict = {
                'bank': bank_name,
                'status': session.get('status', 'unknown'),
                'accounts': len(session.get('accounts', [])),
                'linked': session.get('status') == 'AUTHORIZED',
            }
            access = session.get('access', {})
            if access.get('valid_until'):
                result['valid_until'] = access['valid_until']
            results.append(result)
        except Exception as e:
            results.append({'bank': bank_name, 'status': 'error', 'error': str(e)})

    warning = get_sync_meta(user_slug, 'consent_warning')
    output: dict = {'banks': results}
    if warning:
        output['consent_warning'] = warning

    return json.dumps(output, indent=2)


@register('banking.accounts')
async def accounts(params: dict, user_slug: str) -> str:
    """List linked bank accounts across all banks."""
    accts = await list_accounts(user_slug)
    return json.dumps(accts, indent=2)


@register('banking.balance')
async def balance(params: dict, user_slug: str) -> str:
    """Get current balance from the local cache.

    Falls back to a live API call if cache is empty.
    """
    cached = get_balances(user_slug)
    if cached:
        last_sync = get_sync_meta(user_slug, 'last_sync_at')
        return json.dumps({'balances': cached, 'last_synced': last_sync}, indent=2)

    all_balances: list[dict] = []
    for entry in get_stored_sessions(user_slug):
        session_id = entry.get('session_id', '')
        if not session_id:
            continue
        try:
            session = await get_session(user_slug, session_id)
            for account in session.get('accounts', []):
                uid = account if isinstance(account, str) else account.get('uid', '')
                if uid:
                    bals = await client_get_balances(user_slug, uid)
                    upsert_balances(user_slug, uid, bals)
                    all_balances.extend(bals)
        except Exception:
            pass
    return json.dumps({'balances': all_balances, 'source': 'live'}, indent=2)


@register('banking.transactions')
async def transactions(params: dict, user_slug: str) -> str:
    """Query cached transactions.

    All parameters are optional — returns the most recent transactions
    by default. The agent should set appropriate filters based on the
    user's natural language question.
    """
    date_from = params.get('date_from')
    date_to = params.get('date_to')
    search = params.get('search')
    min_amount = float(params['min_amount']) if params.get('min_amount') else None
    max_amount = float(params['max_amount']) if params.get('max_amount') else None
    limit = int(params.get('limit', '200'))

    rows = get_transactions(
        user_slug,
        date_from=date_from,
        date_to=date_to,
        search=search,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
    )

    last_sync = get_sync_meta(user_slug, 'last_sync_at')
    return json.dumps({'transactions': rows, 'count': len(rows), 'last_synced': last_sync}, indent=2)


@register('banking.sync')
async def manual_sync(params: dict, user_slug: str) -> str:
    """Trigger an immediate sync of transactions and balances from all linked banks.

    When ``user_slug == '_system'`` (the scheduler's system-scope dispatch),
    iterate every live user with banking credentials and sync each. When a
    real slug is passed, sync only that user.
    """
    if user_slug != _SYSTEM_USER:
        summary = await sync_account(user_slug)
        return json.dumps(summary, indent=2)

    slugs = [s for s in _live_user_slugs() if _has_banking_creds(s)]
    if not slugs:
        return json.dumps({'users': [], 'synced_total': 0, 'note': 'no users with banking credentials'}, indent=2)

    per_user: list[dict] = []
    total_synced = 0
    for slug in slugs:
        try:
            summary = await sync_account(slug)
        except Exception as exc:
            log.warning('[banking-sync] user=%s failed: %s', slug, exc)
            per_user.append({'user': slug, 'error': str(exc)})
            continue
        total_synced += int(summary.get('synced', 0))
        per_user.append({'user': slug, **summary})

    return json.dumps({'users': per_user, 'synced_total': total_synced}, indent=2)
