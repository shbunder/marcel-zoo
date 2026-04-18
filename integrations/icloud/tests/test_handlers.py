"""Unit tests for the icloud habitat client.

Tests target ``client.py`` directly rather than going through ``__init__.py``,
because importing the package twice (once by pytest's collection machinery
and once via the test's own import path) would re-trigger ``@register`` and
collide on the kernel's global integration registry. The handlers in
``__init__.py`` are three-line wrappers that delegate to the client; they
are exercised end-to-end by the kernel's discovery + dispatch tests.

These tests monkeypatch ``caldav.DAVClient`` and ``imaplib.IMAP4_SSL`` so
the suite never touches Apple's servers.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any

import pytest

# Load client.py without importing the parent package (which would fire
# @register and conflict with anything else in the same Python process).
_CLIENT_PATH = pathlib.Path(__file__).resolve().parent.parent / 'client.py'
_spec = importlib.util.spec_from_file_location('_icloud_client_under_test', _CLIENT_PATH)
assert _spec is not None and _spec.loader is not None
client = importlib.util.module_from_spec(_spec)
sys.modules['_icloud_client_under_test'] = client
_spec.loader.exec_module(client)


class _FakeVobjValue:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeVevent:
    def __init__(self, **fields: str) -> None:
        for k, v in fields.items():
            setattr(self, k, _FakeVobjValue(v))


class _FakeEvent:
    def __init__(self, vevent: _FakeVevent) -> None:
        class _Inst:
            def __init__(self, ev: _FakeVevent) -> None:
                self.vevent = ev

        self.vobject_instance = _Inst(vevent)


class _FakeCalendar:
    def __init__(self, name: str, events: list[_FakeEvent]) -> None:
        self._name = name
        self._events = events

    def get_display_name(self) -> str:
        return self._name

    def search(self, **_kwargs: Any) -> list[_FakeEvent]:
        return self._events


class _FakePrincipal:
    def __init__(self, calendars: list[_FakeCalendar]) -> None:
        self._cals = calendars

    def calendars(self) -> list[_FakeCalendar]:
        return self._cals


class _FakeDAVClient:
    captured: dict[str, Any] = {}

    def __init__(self, *, url: str, username: str, password: str) -> None:
        type(self).captured = {'url': url, 'username': username, 'password': password}

    def principal(self) -> _FakePrincipal:
        return _FakePrincipal(
            [
                _FakeCalendar(
                    'Personal',
                    [
                        _FakeEvent(
                            _FakeVevent(
                                summary='Dentist',
                                dtstart='2026-04-19 09:00',
                                dtend='2026-04-19 10:00',
                                location='Brussels',
                                description='Cleaning',
                            )
                        ),
                    ],
                ),
            ]
        )


@pytest.fixture
def stub_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``credentials.load`` so the client thinks the user is set up."""
    monkeypatch.setattr(
        client.credentials,
        'load',
        lambda _slug: {'ICLOUD_APPLE_ID': 'test@me.com', 'ICLOUD_APP_PASSWORD': 'app-pw'},
    )


async def test_get_calendar_events_returns_parsed_events(
    stub_credentials: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client.caldav, 'DAVClient', _FakeDAVClient)

    events = await client.get_calendar_events('shaun', days_ahead=3)

    assert events[0]['title'] == 'Dentist'
    assert events[0]['calendar'] == 'Personal'
    assert events[0]['location'] == 'Brussels'
    assert _FakeDAVClient.captured['username'] == 'test@me.com'
    assert _FakeDAVClient.captured['password'] == 'app-pw'
    assert _FakeDAVClient.captured['url'] == 'https://caldav.icloud.com/'


async def test_missing_credentials_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client.credentials, 'load', lambda _slug: {})

    with pytest.raises(RuntimeError, match='ICLOUD_APPLE_ID'):
        await client.get_calendar_events('shaun')


async def test_search_mail_dispatches_to_imap(
    stub_credentials: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeIMAP:
        def __init__(self, host: str, port: int) -> None:
            captured['host'] = host
            captured['port'] = port

        def login(self, user: str, password: str) -> None:
            captured['login'] = (user, password)

        def select(self, _box: str) -> None:
            pass

        def search(self, _charset: Any, criterion: str) -> tuple[str, list[bytes]]:
            captured['criterion'] = criterion
            return 'OK', [b'']

        def fetch(self, _msg_id: bytes, _spec: str) -> tuple[str, list[Any]]:
            return 'OK', []

        def logout(self) -> None:
            captured['logout'] = True

    monkeypatch.setattr(client.imaplib, 'IMAP4_SSL', _FakeIMAP)

    results = await client.search_mail('shaun', query='flight', limit=5)

    assert results == []
    assert captured['host'] == 'imap.mail.me.com'
    assert captured['port'] == 993
    assert captured['login'] == ('test@me.com', 'app-pw')
    assert captured['criterion'] == 'TEXT "flight"'
    assert captured['logout'] is True
