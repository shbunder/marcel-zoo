"""Docker container management — habitat for marcel-zoo.

Registers docker.list, docker.status, docker.restart, and docker.logs
as integration handlers callable through Marcel's ``integration`` tool.

Requires DOCKER_HOST to be set (e.g. unix:///var/run/docker.sock).
See integration.yaml for the declared requires; SKILL.md teaches the
agent how to call each handler; SETUP.md is shown when DOCKER_HOST is
not configured.
"""

from __future__ import annotations

import asyncio

from marcel_core.plugin import register

_DEFAULT_TIMEOUT = 15


async def _run(*args: str) -> tuple[int, str]:
    """Run a docker command and return (returncode, output)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_DEFAULT_TIMEOUT)
    output = stdout.decode().strip() if stdout else ''
    return proc.returncode or 0, output


@register('docker.list')
async def list_containers(params: dict, user_slug: str) -> str:
    """List all Docker containers and their current status."""
    rc, out = await _run('docker', 'ps', '-a', '--format', 'table {{.Names}}\t{{.Status}}\t{{.Image}}')
    if rc != 0:
        return f'Error listing containers:\n{out}'
    return out or '(no containers found)'


@register('docker.status')
async def status(params: dict, user_slug: str) -> str:
    """Check the status of a specific Docker container.

    Params:
        container: Container name (default: plex-server)
    """
    container = params.get('container', 'plex-server')
    rc, out = await _run(
        'docker',
        'inspect',
        '--format',
        '{{.State.Status}} | health={{.State.Health.Status}} | running={{.State.Running}}',
        container,
    )
    if rc != 0:
        return f'Error: container "{container}" not found or docker unavailable.\n{out}'
    return f'{container}: {out}'


@register('docker.restart')
async def restart(params: dict, user_slug: str) -> str:
    """Restart a Docker container.

    Params:
        container: Container name (default: plex-server)
    """
    container = params.get('container', 'plex-server')
    rc, out = await _run('docker', 'restart', container)
    if rc != 0:
        return f'Error restarting "{container}":\n{out}'
    return f'Restarted {container} successfully.'


@register('docker.logs')
async def logs(params: dict, user_slug: str) -> str:
    """Fetch recent logs from a Docker container.

    Params:
        container: Container name (default: plex-server)
        lines: Number of log lines to return (default: 50)
    """
    container = params.get('container', 'plex-server')
    lines = params.get('lines', '50')
    rc, out = await _run('docker', 'logs', '--tail', str(lines), container)
    if rc != 0:
        return f'Error fetching logs for "{container}":\n{out}'
    return out or f'(no recent logs for {container})'
