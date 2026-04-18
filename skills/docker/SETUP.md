---
name: docker
description: Guide the user through setting up Docker container management
---

The user is asking about a Docker container, but Docker management is **not yet configured**.

## How to set up Docker management

Marcel can inspect, restart, and fetch logs for any Docker container on your server. To enable this:

1. **Docker socket access** — set `DOCKER_HOST=unix:///var/run/docker.sock` in `.env.local`
2. **Socket mount** — the Docker socket must be mounted into the Marcel container (already done in `docker-compose.yml`)

Tell the user what's needed and ask if they'd like help setting it up.
