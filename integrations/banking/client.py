"""EnableBanking API client for bank account data.

Handles JWT authentication (RS256 with private key), multi-bank session
management, and account data retrieval (balances, transactions).

Credentials are read from the user's credential store via
:mod:`marcel_core.plugin.credentials`:

    ENABLEBANKING_APP_ID — application UUID (also the .pem filename)

The private key file lives at:
    ``<user_dir>/enablebanking.pem``

Bank sessions are stored as a JSON list under ``ENABLEBANKING_SESSIONS``::

    [{"bank": "KBC", "country": "BE", "session_id": "..."},
     {"bank": "ING", "country": "BE", "session_id": "..."}]

Legacy single-session key ``ENABLEBANKING_SESSION_ID`` is auto-migrated.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import jwt

from marcel_core.plugin import credentials, get_logger, paths

log = get_logger(__name__)

_BASE_URL = 'https://api.enablebanking.com'

SUPPORTED_BANKS: dict[str, dict[str, str]] = {
    'KBC': {'country': 'BE'},
    'ING': {'country': 'BE'},
}


def _app_id(slug: str) -> str:
    """Return the EnableBanking application ID from the user's credential store."""
    creds = credentials.load(slug)
    app_id = creds.get('ENABLEBANKING_APP_ID', '').strip()
    if not app_id:
        raise RuntimeError(f'ENABLEBANKING_APP_ID must be set in credentials for user {slug}')
    return app_id


def _private_key_path(slug: str) -> Path:
    return paths.user_dir(slug) / 'enablebanking.pem'


def _load_private_key(slug: str) -> str:
    """Load the PEM private key for JWT signing."""
    path = _private_key_path(slug)
    if not path.exists():
        raise RuntimeError(
            f'EnableBanking private key not found at {path}. Download it from the EnableBanking dashboard.'
        )
    return path.read_text()


def _make_jwt(slug: str) -> str:
    """Create a signed JWT for EnableBanking API authentication."""
    app_id = _app_id(slug)
    private_key = _load_private_key(slug)
    now = int(time.time())
    payload = {
        'iss': 'enablebanking.com',
        'aud': 'api.enablebanking.com',
        'iat': now,
        'exp': now + 3600,
    }
    return jwt.encode(payload, private_key, algorithm='RS256', headers={'kid': app_id})


def _load_sessions(slug: str) -> list[dict[str, str]]:
    """Load all bank sessions from the credential store.

    Auto-migrates the legacy single-session key ``ENABLEBANKING_SESSION_ID``
    to the new ``ENABLEBANKING_SESSIONS`` JSON list on first access.
    """
    creds = credentials.load(slug)

    raw = creds.get('ENABLEBANKING_SESSIONS', '')
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.warning('Corrupt ENABLEBANKING_SESSIONS for user %s, resetting', slug)
            return []

    legacy_sid = creds.get('ENABLEBANKING_SESSION_ID', '').strip()
    if legacy_sid:
        sessions = [{'bank': 'KBC', 'country': 'BE', 'session_id': legacy_sid}]
        _save_sessions(slug, sessions, _creds=creds)
        log.info('Migrated legacy ENABLEBANKING_SESSION_ID to ENABLEBANKING_SESSIONS for user %s', slug)
        return sessions

    return []


def _save_sessions(
    slug: str,
    sessions: list[dict[str, str]],
    *,
    _creds: dict[str, str] | None = None,
) -> None:
    """Persist bank sessions to the credential store."""
    creds = _creds if _creds is not None else credentials.load(slug)
    creds['ENABLEBANKING_SESSIONS'] = json.dumps(sessions)
    creds.pop('ENABLEBANKING_SESSION_ID', None)
    credentials.save(slug, creds)


def get_stored_sessions(slug: str) -> list[dict[str, str]]:
    """Return all stored bank session entries (public API for sync module)."""
    return _load_sessions(slug)


def _session_id_for_bank(slug: str, bank: str) -> str:
    """Return the session ID for a specific bank, or raise if not linked."""
    for entry in _load_sessions(slug):
        if entry.get('bank', '').upper() == bank.upper():
            return entry['session_id']
    raise RuntimeError(f'No {bank} bank link found. Run banking.setup with bank="{bank}" to link your account.')


async def _authed_get(slug: str, path: str, *, params: dict[str, str] | None = None) -> Any:
    """Make an authenticated GET request to the EnableBanking API."""
    token = _make_jwt(slug)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f'{_BASE_URL}{path}',
            headers={'Authorization': f'Bearer {token}'},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def _authed_post(slug: str, path: str, *, json: dict[str, Any]) -> Any:
    """Make an authenticated POST request to the EnableBanking API."""
    token = _make_jwt(slug)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f'{_BASE_URL}{path}',
            headers={'Authorization': f'Bearer {token}'},
            json=json,
        )
        resp.raise_for_status()
        return resp.json()


async def _authed_delete(slug: str, path: str) -> None:
    """Make an authenticated DELETE request to the EnableBanking API."""
    token = _make_jwt(slug)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(
            f'{_BASE_URL}{path}',
            headers={'Authorization': f'Bearer {token}'},
        )
        resp.raise_for_status()


async def start_authorization(
    slug: str,
    redirect_url: str = 'https://enablebanking.com',
    *,
    bank: str = 'KBC',
    country: str = 'BE',
) -> dict[str, Any]:
    """Start the bank authorization flow.

    Returns a dict with ``url`` (redirect the user here) and
    ``authorization_id``.
    """
    from datetime import UTC, datetime, timedelta

    valid_until = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    data = await _authed_post(
        slug,
        '/auth',
        json={
            'access': {'valid_until': valid_until},
            'aspsp': {'name': bank, 'country': country},
            'state': f'marcel-{slug}-{bank.lower()}',
            'redirect_url': redirect_url,
            'psu_type': 'personal',
        },
    )
    log.info('Started %s authorization for user %s', bank, slug)
    return data


async def create_session(
    slug: str,
    auth_code: str,
    *,
    bank: str = 'KBC',
    country: str = 'BE',
) -> dict[str, Any]:
    """Exchange an authorization code for a session.

    Persists the session_id in the user's credential store alongside any
    existing sessions. Replaces an existing session for the same bank.
    Returns the full session response including account list.
    """
    data = await _authed_post(slug, '/sessions', json={'code': auth_code})
    session_id = data.get('session_id', '')
    if session_id:
        sessions = _load_sessions(slug)
        sessions = [s for s in sessions if s.get('bank', '').upper() != bank.upper()]
        sessions.append({'bank': bank, 'country': country, 'session_id': session_id})
        _save_sessions(slug, sessions)
        log.info('Created %s session %s for user %s', bank, session_id, slug)
    return data


async def get_session(slug: str, session_id: str) -> dict[str, Any]:
    """Return the session status and account list for a specific session ID."""
    return await _authed_get(slug, f'/sessions/{session_id}')


async def get_session_for_bank(slug: str, bank: str) -> dict[str, Any]:
    """Return the session status for a specific bank."""
    sid = _session_id_for_bank(slug, bank)
    return await _authed_get(slug, f'/sessions/{sid}')


async def list_accounts(slug: str) -> list[dict[str, Any]]:
    """Return account data from all linked bank sessions."""
    all_accounts: list[dict[str, Any]] = []
    for entry in _load_sessions(slug):
        try:
            session = await get_session(slug, entry['session_id'])
            bank_name = entry.get('bank', 'Unknown')
            for acct in session.get('accounts', []):
                if isinstance(acct, str):
                    all_accounts.append({'uid': acct, 'bank': bank_name})
                else:
                    acct['bank'] = bank_name
                    all_accounts.append(acct)
        except Exception:
            log.warning('Failed to fetch accounts for %s session', entry.get('bank'))
    return all_accounts


async def get_balances(slug: str, account_uid: str) -> list[dict[str, Any]]:
    """Return balance entries for a specific account."""
    data = await _authed_get(slug, f'/accounts/{account_uid}/balances')
    return data.get('balances', [])


async def get_transactions(
    slug: str,
    account_uid: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    continuation_key: str | None = None,
) -> dict[str, Any]:
    """Return transactions for an account.

    Returns a dict with ``transactions`` list and optional
    ``continuation_key`` for pagination.
    """
    params: dict[str, str] = {}
    if date_from:
        params['date_from'] = date_from
    if date_to:
        params['date_to'] = date_to
    if continuation_key:
        params['continuation_key'] = continuation_key
    return await _authed_get(
        slug,
        f'/accounts/{account_uid}/transactions',
        params=params,
    )


async def get_all_transactions(
    slug: str,
    account_uid: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all transactions, handling pagination automatically."""
    all_txs: list[dict[str, Any]] = []
    cont_key: str | None = None

    while True:
        data = await get_transactions(
            slug,
            account_uid,
            date_from=date_from,
            date_to=date_to,
            continuation_key=cont_key,
        )
        all_txs.extend(data.get('transactions', []))
        cont_key = data.get('continuation_key')
        if not cont_key:
            break

    return all_txs
