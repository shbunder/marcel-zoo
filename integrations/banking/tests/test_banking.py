"""Unit tests for the banking habitat — cache, client, and sync.

Loads ``cache.py``, ``client.py``, and ``sync.py`` under a synthetic
parent package via ``importlib``, bypassing ``__init__.py`` so
``@register`` does not collide on the kernel's global integration
registry. The handlers in ``__init__.py`` are thin wrappers over cache +
client + sync; they are exercised end-to-end by the kernel's discovery +
dispatch tests in the Marcel repo.

A per-test ``tmp_path`` is wired into :mod:`marcel_core.storage._root` so
the SQLite DB and credential files land in an isolated directory.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from marcel_core.storage import _root

_HABITAT_DIR = pathlib.Path(__file__).resolve().parent.parent
_PKG = '_banking_under_test'


def _load_submodule(submodule: str) -> Any:
    qualified = f'{_PKG}.{submodule}'
    path = _HABITAT_DIR / f'{submodule}.py'
    spec = importlib.util.spec_from_file_location(qualified, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _PKG
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


_parent = types.ModuleType(_PKG)
_parent.__path__ = [str(_HABITAT_DIR)]
sys.modules[_PKG] = _parent

cache = _load_submodule('cache')
client = _load_submodule('client')
sync = _load_submodule('sync')


@pytest.fixture(autouse=True)
def _isolate(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
    (tmp_path / 'users' / 'test').mkdir(parents=True)


def _make_tx(
    *,
    amount: str = '42.50',
    indicator: str = 'DBIT',
    counterparty: str = 'Colruyt',
    booking_date: str = '2026-04-01',
    tx_id: str = 'tx-001',
    remittance: str = 'Payment for groceries',
) -> dict:
    party_field = 'creditor' if indicator == 'DBIT' else 'debtor'
    return {
        'transaction_id': tx_id,
        'booking_date': booking_date,
        'value_date': booking_date,
        'transaction_amount': {'amount': amount, 'currency': 'EUR'},
        'credit_debit_indicator': indicator,
        party_field: {'name': counterparty},
        f'{party_field}_account': {'iban': 'BE12345678901234'},
        'remittance_information': [remittance],
        'status': 'BOOK',
        'bank_transaction_code': {'description': 'Payment'},
    }


def _make_balance(
    *,
    amount: str = '1234.56',
    balance_type: str = 'CLBD',
    ref_date: str = '2026-04-01',
) -> dict:
    return {
        'balance_amount': {'amount': amount, 'currency': 'EUR'},
        'balance_type': balance_type,
        'reference_date': ref_date,
    }


# ── Cache: transactions ──────────────────────────────────────────────────────


class TestCacheTransactions:
    def test_upsert_and_query(self) -> None:
        tx = _make_tx()
        count = cache.upsert_transactions('test', 'acct-1', [tx])
        assert count == 1

        rows = cache.get_transactions('test')
        assert len(rows) == 1
        assert rows[0]['counterparty_name'] == 'Colruyt'
        assert rows[0]['amount'] == -42.50
        assert rows[0]['booking_date'] == '2026-04-01'

    def test_credit_transaction_stays_positive(self) -> None:
        tx = _make_tx(indicator='CRDT', amount='1000.00', counterparty='Employer')
        cache.upsert_transactions('test', 'acct-1', [tx])
        rows = cache.get_transactions('test')
        assert rows[0]['amount'] == 1000.0

    def test_upsert_is_idempotent(self) -> None:
        tx = _make_tx()
        cache.upsert_transactions('test', 'acct-1', [tx])
        cache.upsert_transactions('test', 'acct-1', [tx])
        rows = cache.get_transactions('test')
        assert len(rows) == 1

    def test_upsert_updates_existing(self) -> None:
        tx = _make_tx(amount='42.50')
        cache.upsert_transactions('test', 'acct-1', [tx])

        tx['transaction_amount']['amount'] = '99.99'
        cache.upsert_transactions('test', 'acct-1', [tx])

        rows = cache.get_transactions('test')
        assert len(rows) == 1
        assert rows[0]['amount'] == -99.99

    def test_filter_by_date_range(self) -> None:
        txs = [
            _make_tx(tx_id='tx-jan', booking_date='2026-01-15'),
            _make_tx(tx_id='tx-feb', booking_date='2026-02-15'),
            _make_tx(tx_id='tx-mar', booking_date='2026-03-15'),
        ]
        cache.upsert_transactions('test', 'acct-1', txs)

        rows = cache.get_transactions('test', date_from='2026-02-01', date_to='2026-02-28')
        assert len(rows) == 1
        assert rows[0]['booking_date'] == '2026-02-15'

    def test_filter_by_search(self) -> None:
        txs = [
            _make_tx(tx_id='tx-1', counterparty='Colruyt'),
            _make_tx(tx_id='tx-2', counterparty='Delhaize'),
        ]
        cache.upsert_transactions('test', 'acct-1', txs)

        rows = cache.get_transactions('test', search='Colruyt')
        assert len(rows) == 1
        assert rows[0]['counterparty_name'] == 'Colruyt'

    def test_filter_by_amount_range(self) -> None:
        txs = [
            _make_tx(tx_id='tx-small', amount='10.00'),
            _make_tx(tx_id='tx-big', amount='500.00'),
        ]
        cache.upsert_transactions('test', 'acct-1', txs)

        rows = cache.get_transactions('test', max_amount=-100.0)
        assert len(rows) == 1
        assert rows[0]['amount'] == -500.0

    def test_limit(self) -> None:
        txs = [_make_tx(tx_id=f'tx-{i}', booking_date=f'2026-01-{i + 1:02d}') for i in range(10)]
        cache.upsert_transactions('test', 'acct-1', txs)
        rows = cache.get_transactions('test', limit=3)
        assert len(rows) == 3

    def test_multiple_accounts(self) -> None:
        cache.upsert_transactions('test', 'acct-1', [_make_tx(tx_id='tx-a1')])
        cache.upsert_transactions('test', 'acct-2', [_make_tx(tx_id='tx-a2')])
        rows = cache.get_transactions('test')
        assert len(rows) == 2

    def test_composite_id_fallback(self) -> None:
        tx = {
            'booking_date': '2026-04-01',
            'transaction_amount': {'amount': '25.00', 'currency': 'EUR'},
            'credit_debit_indicator': 'DBIT',
            'creditor': {'name': 'Test Shop'},
            'remittance_information': ['Purchase'],
        }
        count = cache.upsert_transactions('test', 'acct-1', [tx])
        assert count == 1
        rows = cache.get_transactions('test')
        assert len(rows) == 1

    def test_null_remittance_and_bank_tx_code(self) -> None:
        tx = {
            'transaction_id': 'tx-null-fields',
            'booking_date': '2026-04-01',
            'transaction_amount': {'amount': '10.00', 'currency': 'EUR'},
            'credit_debit_indicator': 'DBIT',
            'creditor': {'name': 'Shop'},
            'remittance_information': None,
            'bank_transaction_code': None,
        }
        count = cache.upsert_transactions('test', 'acct-1', [tx])
        assert count == 1
        rows = cache.get_transactions('test')
        assert len(rows) == 1
        assert rows[0]['remittance_info'] == ''
        assert rows[0]['bank_tx_code'] == ''


# ── Cache: balances ──────────────────────────────────────────────────────────


class TestCacheBalances:
    def test_upsert_and_query(self) -> None:
        bal = _make_balance()
        cache.upsert_balances('test', 'acct-1', [bal])

        rows = cache.get_balances('test')
        assert len(rows) == 1
        assert rows[0]['amount'] == 1234.56
        assert rows[0]['balance_type'] == 'CLBD'

    def test_upsert_updates_existing(self) -> None:
        cache.upsert_balances('test', 'acct-1', [_make_balance(amount='100.00')])
        cache.upsert_balances('test', 'acct-1', [_make_balance(amount='200.00')])

        rows = cache.get_balances('test')
        assert len(rows) == 1
        assert rows[0]['amount'] == 200.0

    def test_multiple_balance_types(self) -> None:
        bals = [
            _make_balance(balance_type='CLBD', amount='100.00'),
            _make_balance(balance_type='ITAV', amount='150.00'),
        ]
        cache.upsert_balances('test', 'acct-1', bals)
        rows = cache.get_balances('test')
        assert len(rows) == 2


# ── Cache: sync metadata ────────────────────────────────────────────────────


class TestSyncMeta:
    def test_set_and_get(self) -> None:
        cache.set_sync_meta('test', 'last_sync_date', '2026-04-01')
        assert cache.get_sync_meta('test', 'last_sync_date') == '2026-04-01'

    def test_get_missing_returns_none(self) -> None:
        assert cache.get_sync_meta('test', 'nonexistent') is None

    def test_update_overwrites(self) -> None:
        cache.set_sync_meta('test', 'key', 'first')
        cache.set_sync_meta('test', 'key', 'second')
        assert cache.get_sync_meta('test', 'key') == 'second'


# ── Cache: helpers ───────────────────────────────────────────────────────────


class TestCacheHelpers:
    def test_tx_internal_id_prefers_transaction_id(self) -> None:
        tx = {'transaction_id': 'tx-1', 'entry_reference': 'ref-1'}
        assert cache._tx_internal_id(tx, 'acct') == 'tx-1'

    def test_tx_internal_id_falls_back_to_entry_reference(self) -> None:
        tx = {'entry_reference': 'ref-1'}
        assert cache._tx_internal_id(tx, 'acct') == 'ref-1'

    def test_tx_internal_id_composite_fallback(self) -> None:
        tx = {
            'booking_date': '2026-04-01',
            'transaction_amount': {'amount': '25.00'},
            'creditor': {'name': 'Shop'},
            'remittance_information': ['Purchase'],
        }
        result = cache._tx_internal_id(tx, 'acct-1')
        assert 'acct-1' in result
        assert '2026-04-01' in result

    def test_extract_iban_creditor(self) -> None:
        tx = {'creditor_account': {'iban': 'BE123'}}
        assert cache._extract_iban(tx) == 'BE123'

    def test_extract_iban_debtor(self) -> None:
        tx = {'debtor_account': {'iban': 'BE456'}}
        assert cache._extract_iban(tx) == 'BE456'

    def test_extract_iban_identification_fallback(self) -> None:
        tx = {'creditor_account': {'identification': 'BE789'}}
        assert cache._extract_iban(tx) == 'BE789'

    def test_extract_iban_none(self) -> None:
        assert cache._extract_iban({}) == ''


# ── Client: multi-session storage ───────────────────────────────────────────


class TestMultiSessionStorage:
    def test_load_sessions_empty(self) -> None:
        with patch.object(client.credentials, 'load', return_value={}):
            assert client._load_sessions('test') == []

    def test_load_sessions_json(self) -> None:
        sessions = [{'bank': 'KBC', 'country': 'BE', 'session_id': 'sid-1'}]
        creds = {'ENABLEBANKING_SESSIONS': json.dumps(sessions)}
        with patch.object(client.credentials, 'load', return_value=creds):
            result = client._load_sessions('test')
            assert len(result) == 1
            assert result[0]['bank'] == 'KBC'

    def test_load_sessions_migrates_legacy(self) -> None:
        creds = {'ENABLEBANKING_SESSION_ID': 'legacy-sid'}
        with (
            patch.object(client.credentials, 'load', return_value=creds),
            patch.object(client.credentials, 'save') as mock_save,
        ):
            result = client._load_sessions('test')
            assert len(result) == 1
            assert result[0]['bank'] == 'KBC'
            assert result[0]['session_id'] == 'legacy-sid'
            mock_save.assert_called_once()

    def test_session_id_for_bank(self) -> None:
        sessions = [
            {'bank': 'KBC', 'country': 'BE', 'session_id': 'sid-kbc'},
            {'bank': 'ING', 'country': 'BE', 'session_id': 'sid-ing'},
        ]
        with patch.object(client, '_load_sessions', return_value=sessions):
            assert client._session_id_for_bank('test', 'KBC') == 'sid-kbc'
            assert client._session_id_for_bank('test', 'ING') == 'sid-ing'
            with pytest.raises(RuntimeError, match='No Belfius'):
                client._session_id_for_bank('test', 'Belfius')


# ── Sync ─────────────────────────────────────────────────────────────────────


class TestSync:
    @pytest.mark.asyncio
    async def test_sync_no_sessions(self) -> None:
        with patch.object(sync, 'get_stored_sessions', return_value=[]):
            summary = await sync.sync_account('test')
            assert any('No bank links' in w for w in summary['warnings'])

    @pytest.mark.asyncio
    async def test_sync_session_not_authorized(self) -> None:
        sessions = [{'bank': 'KBC', 'country': 'BE', 'session_id': 'sid-1'}]
        with (
            patch.object(sync, 'get_stored_sessions', return_value=sessions),
            patch.object(sync, 'get_session', new_callable=AsyncMock, return_value={'status': 'EXPIRED', 'accounts': []}),
        ):
            summary = await sync.sync_account('test')
            assert any('expected AUTHORIZED' in w for w in summary['warnings'])

    @pytest.mark.asyncio
    async def test_sync_single_bank_success(self) -> None:
        sessions = [{'bank': 'KBC', 'country': 'BE', 'session_id': 'sid-1'}]
        mock_session = {
            'status': 'AUTHORIZED',
            'accounts': [{'uid': 'acct-1'}],
        }

        with (
            patch.object(sync, 'get_stored_sessions', return_value=sessions),
            patch.object(sync, 'get_session', new_callable=AsyncMock, return_value=mock_session),
            patch.object(sync, 'get_balances', new_callable=AsyncMock, return_value=[_make_balance()]),
            patch.object(sync, 'get_all_transactions', new_callable=AsyncMock, return_value=[_make_tx()]),
        ):
            summary = await sync.sync_account('test')
            assert summary['synced'] == 1
            assert len(summary['banks']) == 1
            assert summary['banks'][0]['bank'] == 'KBC'
            assert not summary['warnings']

            rows = cache.get_transactions('test')
            assert len(rows) == 1
            bals = cache.get_balances('test')
            assert len(bals) == 1

    @pytest.mark.asyncio
    async def test_sync_multi_bank(self) -> None:
        sessions = [
            {'bank': 'KBC', 'country': 'BE', 'session_id': 'sid-kbc'},
            {'bank': 'ING', 'country': 'BE', 'session_id': 'sid-ing'},
        ]
        kbc_session = {'status': 'AUTHORIZED', 'accounts': ['acct-kbc']}
        ing_session = {'status': 'AUTHORIZED', 'accounts': ['acct-ing']}

        async def mock_get_session(_slug: str, sid: str) -> dict[str, Any]:
            return kbc_session if sid == 'sid-kbc' else ing_session

        with (
            patch.object(sync, 'get_stored_sessions', return_value=sessions),
            patch.object(sync, 'get_session', new_callable=AsyncMock, side_effect=mock_get_session),
            patch.object(sync, 'get_balances', new_callable=AsyncMock, return_value=[_make_balance()]),
            patch.object(sync, 'get_all_transactions', new_callable=AsyncMock, return_value=[_make_tx()]),
        ):
            summary = await sync.sync_account('test')
            assert summary['synced'] == 2
            assert len(summary['banks']) == 2
            bank_names = {b['bank'] for b in summary['banks']}
            assert bank_names == {'KBC', 'ING'}

    @pytest.mark.asyncio
    async def test_check_consent_expiry_warns(self) -> None:
        sessions = [{'bank': 'KBC', 'country': 'BE', 'session_id': 'sid-1'}]
        valid_until = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        mock_session = {
            'status': 'AUTHORIZED',
            'access': {'valid_until': valid_until},
        }

        with (
            patch.object(sync, 'get_stored_sessions', return_value=sessions),
            patch.object(sync, 'get_session', new_callable=AsyncMock, return_value=mock_session),
        ):
            warnings = await sync.check_consent_expiry('test')
            assert len(warnings) == 1
            assert 'KBC' in warnings[0]
            assert 'expires' in warnings[0]

    @pytest.mark.asyncio
    async def test_check_consent_expiry_ok(self) -> None:
        sessions = [{'bank': 'KBC', 'country': 'BE', 'session_id': 'sid-1'}]
        valid_until = (datetime.now(UTC) + timedelta(days=80)).isoformat()
        mock_session = {
            'status': 'AUTHORIZED',
            'access': {'valid_until': valid_until},
        }

        with (
            patch.object(sync, 'get_stored_sessions', return_value=sessions),
            patch.object(sync, 'get_session', new_callable=AsyncMock, return_value=mock_session),
        ):
            warnings = await sync.check_consent_expiry('test')
            assert len(warnings) == 0
