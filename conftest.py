"""pytest bootstrap for marcel-zoo habitats.

The zoo currently has no pyproject.toml of its own — habitat tests run
via the kernel's virtualenv (``~/projects/marcel/.venv``) since they
import from ``marcel_core``. This conftest adds the kernel ``src/`` to
``sys.path`` so ``import marcel_core`` resolves, and wires the asyncio
plugin to ``auto`` mode so ``async def test_*`` functions Just Work.

Run from the zoo root::

    python -m pytest integrations/

When the zoo gets its own ``pyproject.toml`` under ISSUE-2ccc10's dep
decision, this file gets folded into proper ``[tool.pytest.ini_options]``.
"""

from __future__ import annotations

import pathlib
import sys

_KERNEL_SRC = pathlib.Path('~/projects/marcel/src').expanduser().resolve()
if _KERNEL_SRC.is_dir() and str(_KERNEL_SRC) not in sys.path:
    sys.path.insert(0, str(_KERNEL_SRC))


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    pass
