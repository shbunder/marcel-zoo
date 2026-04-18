# marcel-zoo

Habitats for [Marcel](https://github.com/shbunder/marcel) — modular components
discovered at startup by the Marcel kernel.

A habitat is a self-contained directory holding everything one component needs:
code, prompts, schemas, tests. The Marcel kernel ships none of these — point
`MARCEL_ZOO_DIR` at this checkout to install them.

## Layout

```
integrations/<name>/   # Handler code + integration.yaml (provides / requires)
skills/<name>/         # SKILL.md (depends_on:) + SETUP.md fallback
channels/<name>/       # Transport plugins (Telegram, …) — TBD
jobs/<name>/           # Scheduled tasks — TBD
agents/<name>/         # Subagent definitions — TBD
users/<slug>/          # Per-user working dir (gitignored)
```

## Setup

```bash
git clone https://github.com/shbunder/marcel-zoo.git ~/projects/marcel-zoo
echo 'MARCEL_ZOO_DIR=~/projects/marcel-zoo' >> ~/projects/marcel/.env.local
```

Restart Marcel — habitats are discovered at startup.
