---
name: docker
description: Manage Docker containers on the home NUC
depends_on:
  - docker
---

You have access to the `integration` tool to inspect and manage Docker containers.

## Available commands

### docker.list

List all containers and their current status.

```
integration(id="docker.list")
```

Use this when the user wants an overview of what's running on the server, or when diagnosing an unknown issue.

### docker.status

Check the status of a specific container.

```
integration(id="docker.status", params={"container": "<name>"})
```

Use this to check if a container is running, stopped, or unhealthy. Default container is `plex-server`.

### docker.restart

Restart a container.

```
integration(id="docker.restart", params={"container": "<name>"})
```

Use this when a container is unresponsive, throwing errors, or the user explicitly asks to restart it. The container will be briefly unavailable during restart.

### docker.logs

Fetch recent logs from a container.

```
integration(id="docker.logs", params={"container": "<name>", "lines": "100"})
```

Use this to diagnose errors or unexpected behaviour. Default: 50 lines. Always check logs before recommending a restart if the user reports a specific error.

## Known containers

| Container | Purpose |
|-----------|---------|
| `plex-server` | Plex Media Server |

When the user asks about "Plex" without specifying a container name, use `plex-server`.

## Notes

- All commands talk to the Docker daemon via `DOCKER_HOST` (socket on the NUC).
- A restart takes a few seconds — warn the user that the service will be briefly unavailable.
- If a container keeps crashing, check logs before restarting again.
