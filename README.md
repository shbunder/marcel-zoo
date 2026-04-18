# marcel-zoo

Habitats for [Marcel](https://github.com/shbunder/marcel) — modular components
discovered at startup by the Marcel kernel.

The kernel ships none of this. Point `MARCEL_ZOO_DIR` at a checkout of this
repo and each habitat's contents are loaded on startup.

## Setup

```bash
git clone https://github.com/shbunder/marcel-zoo.git ~/projects/marcel-zoo
echo 'MARCEL_ZOO_DIR=~/projects/marcel-zoo' >> ~/projects/marcel/.env.local
```

Restart Marcel.

## Habitats

A **habitat** is a top-level category directory. Each one holds any number of
**parks** — the actual components, one per subdirectory. Most real features
live across several habitats at once: a park in `integrations/` registers the
code, a matching park in `skills/` teaches the agent how to call it, and so on.

### 🔌 integrations

```
integrations/<name>/
  __init__.py          # @register('<name>.<verb>') handlers
  integration.yaml     # provides: / requires: (env, credentials, packages)
```

The executable layer. A park here registers one or more async handlers with
the kernel via `marcel_core.plugin.register`. Each handler receives
`(params: dict, user_slug: str)` and returns a string the agent can quote
back. `integration.yaml` declares what the park `provides:` (the handler IDs)
and `requires:` before it can load — environment variables, per-user
credentials, Python packages. A park with unmet requirements stays dormant
until its requirements are met.

### 🧠 skills

```
skills/<name>/
  SKILL.md             # always loaded, or loaded when its dependency is live
  SETUP.md             # optional — shown when a dependency isn't met
```

The prompting layer. A skill is plain markdown that gets injected into the
agent's context. It documents what the agent can do, the parameters involved,
and — crucially — *when* to reach for it.

Skills don't require an integration. A park here can be:

- **Standalone** — pure guidance, process, or reference material with no
  `depends_on:`. Always loaded. Useful for teaching the agent a workflow, a
  house style, or domain knowledge that needs no code to act on.
- **Paired with an integration** — `SKILL.md` carries
  `depends_on: [<integration>]` in its frontmatter and is only injected once
  that integration is live. `SETUP.md` is the fallback: if the user asks
  about the feature while the integration is unconfigured, the agent uses it
  to walk them through onboarding instead of failing silently.

`SETUP.md` is only meaningful for the paired case — a standalone skill has
nothing to set up.

### 📡 channels — TBD

```
channels/<name>/
```

Transport plugins. A park here defines how users reach Marcel — Telegram, a
web UI, a CLI, email, etc. Not yet wired up.

### ⏰ jobs — TBD

```
jobs/<name>/
```

Scheduled tasks. A park here runs on a cron-like schedule rather than in
response to a user message. Not yet wired up.

### 🤖 agents — TBD

```
agents/<name>/
```

Subagent definitions — specialised agents Marcel can delegate to for scoped
tasks. Not yet wired up.

### 👤 users

```
users/<slug>/
```

Per-user working directories. Gitignored. Holds credential stores, scratch
state, and anything else a park writes on a user's behalf. Not edited by
hand.

## Adding your own park to a habitat

A park is a single subdirectory inside one habitat. Most features need a
matching park in two habitats — `integrations/` for the code and `skills/`
for the prompting — but nothing forces that coupling: a pure skill or a
headless job is fine on its own.

1. **Pick a name.** Lowercase, no spaces. Reuse the same name across every
   habitat the park spans (`integrations/hue/` and `skills/hue/`, not
   `integrations/hue/` and `skills/philips-hue/`).

2. **Add the files the habitat expects.** The contract for each habitat is
   listed in the section above. At minimum an `integrations/` park needs
   `__init__.py` and `integration.yaml`; a `skills/` park needs `SKILL.md`
   (plus `SETUP.md` if it depends on an integration that may not be
   configured).

3. **Declare requirements honestly.** Anything your park needs to run —
   env vars, credentials, extra packages — goes in `integration.yaml` under
   `requires:`. The kernel uses this to decide whether to load the park or
   surface the `SETUP.md` instead.

4. **Write `SETUP.md` from the user's side.** It's the onboarding script the
   agent reads aloud when requirements aren't met. Write it as instructions
   *to the user*, not notes to yourself.

5. **Restart Marcel.** Habitats are rescanned on startup. If `integration.yaml`
   parses and `requires:` is satisfied, the park is live.

Each park may ship its own `README.md` documenting its internals, command
inventory, quirks, or test setup. Keep that detail in the park — this
top-level README stays about habitats.
