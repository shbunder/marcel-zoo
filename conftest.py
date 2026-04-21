"""pytest bootstrap for marcel-zoo habitats.

Habitat tests run against the kernel's virtualenv (``~/projects/marcel/.venv``)
because they import from ``marcel_core``. This conftest adds the kernel
``src/`` to ``sys.path`` so ``import marcel_core`` resolves. Pytest config
(asyncio mode, testpaths) lives in ``pyproject.toml`` under
``[tool.pytest.ini_options]``.

Run from the zoo root::

    python -m pytest integrations/

Session C of ISSUE-63a946 will replace the ``sys.path`` shim with a proper
editable install against marcel-core — at which point this bootstrap goes
away.
"""

from __future__ import annotations

import pathlib
import sys

_KERNEL_SRC = pathlib.Path('~/projects/marcel/src').expanduser().resolve()
if _KERNEL_SRC.is_dir() and str(_KERNEL_SRC) not in sys.path:
    sys.path.insert(0, str(_KERNEL_SRC))


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    pass
