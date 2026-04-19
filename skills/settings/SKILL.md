---
name: settings
description: Manage Marcel's preferences — change the AI model per channel, list available models
preferred_tier: fast
---

You can change which AI model Marcel uses on any channel, or ask what models are available.

## Available actions

### list_models

List all models available to Marcel.

```
marcel(action="list_models")
```

Returns a list of model IDs and their display names.

### get_model

Get the current model for a specific channel. Defaults to the current channel if name is omitted.

```
marcel(action="get_model", name="telegram")
marcel(action="get_model")
```

### set_model

Set the preferred model for a channel. The choice is saved and persists across sessions.
Pass `name` as `"channel:provider:model"` — the model is a fully-qualified
pydantic-ai string (any pydantic-ai-supported provider:model is accepted).

```
marcel(action="set_model", name="telegram:anthropic:claude-opus-4-6")
marcel(action="set_model", name="cli:openai:gpt-4o")
```

## Usage patterns

- User asks "what models are available?" -> call `list_models`, present the list clearly
- User says "use opus" / "switch to opus" -> clarify which channel if ambiguous, then call `set_model`
- User says "what model are you using?" -> call `get_model` (defaults to current channel)
- When channel is clear from context (e.g., user is in Telegram), use that channel directly without asking

**Current channel** is available in your context as the originating channel for this conversation.
