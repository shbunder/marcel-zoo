"""Per-habitat conftest for telegram channel tests.

Loads the habitat (the parent directory) as the Python package
``marcel_core.channels.telegram`` so the test files' existing import
paths (``from marcel_core.channels.telegram import sessions``,
``monkeypatch.setattr('marcel_core.channels.telegram.webhook...', ...)``,
etc.) resolve against this zoo-local copy.

Rationale: the telegram code moved from the kernel (ISSUE-7d6b3f
stage 4c). Rewriting every test's import path to a new namespace is a
mechanical change with no behavioural value — aliasing the module is
cheaper, and production uses the kernel's dynamic loader under the
``_marcel_ext_channels.telegram`` namespace anyway. Tests and runtime
load the same code via slightly different paths; that is acceptable
because both paths exercise the same bytes on disk.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

_HABITAT_DIR = pathlib.Path(__file__).resolve().parent.parent
_MODULE = 'marcel_core.channels.telegram'


def _load() -> None:
    if _MODULE in sys.modules:
        return

    channels_pkg = importlib.import_module('marcel_core.channels')

    init_py = _HABITAT_DIR / '__init__.py'
    spec = importlib.util.spec_from_file_location(
        _MODULE,
        init_py,
        submodule_search_locations=[str(_HABITAT_DIR)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE] = module
    # Attach to the parent package so ``marcel_core.channels.telegram``
    # resolves via attribute lookup (pytest's monkeypatch.setattr does
    # this chain). Without this, ``getattr(channels_pkg, 'telegram')``
    # fails even though ``sys.modules`` has the entry.
    channels_pkg.telegram = module  # type: ignore[attr-defined]
    spec.loader.exec_module(module)


_load()
