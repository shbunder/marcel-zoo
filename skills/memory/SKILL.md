---
name: memory
description: Manage conversation memory — search past conversations, recall facts, and compress the current conversation
requires: {}
---

# Memory Management

Marcel has memory actions via the `marcel` tool that work together to give you both short-term conversational recall and long-term fact memory.

## Actions

### marcel(action="search_memory", query="...")
Search extracted facts (preferences, contacts, decisions, schedules) by keyword. Returns short snippets for matching files.
**Use when:** the user asks "what's my...", "do you remember my...", or any factual recall where you don't already know the exact memory name.

### marcel(action="read_memory", name="...")
Load the full contents of a specific memory file by name. The system prompt contains a compact memory index (one line per file) — use `read_memory` to pull the full body of any entry.
**Use when:** the memory index shows a relevant entry (e.g. `family`, `calendars`) and you need the full details, or when the user asks about a topic that clearly matches one of the listed memory names.

### marcel(action="save_memory", name="...", message="...")
Save a new memory file or overwrite an existing one. `name` is the filename (without `.md`), `message` is the full file body including YAML frontmatter.
**Use when:** the user shares durable facts, preferences, or context that should survive past the current conversation.

### marcel(action="search_conversations", query="...")
Search past conversation segments by keyword. Returns matching messages with surrounding context from older (summarized) conversation segments.
**Use when:** the user asks "remember when we talked about...", "what did you say about...", or when you need context from a past discussion that isn't in your current context window.

### marcel(action="compact")
Manually compress the current conversation segment into a summary. Opens a fresh segment.
**Use when:** the topic has shifted significantly, the user asks to "clean up" or "compress", or the context feels cluttered.

## Patterns

- The system prompt's `# Memory` block is an **index** — names and descriptions only. Full bodies are loaded on demand with `read_memory`.
- When the user asks about a topic whose name you see in the index, call `read_memory` directly — skip `search_memory` (it's for fuzzy/unknown matches).
- When the user references something from the past, try `search_memory` first (fast, factual, keyword-matched). If that misses, fall back to `search_conversations` (broader, contextual).
- Don't search proactively — only when the user's question requires historical context that isn't already in your conversation summary.
- After compaction, briefly mention what key points were preserved so the user knows what you'll remember.
- The `/forget` command (Telegram) triggers the same compaction as `marcel(action="compact")`.

## How memory works

Your conversation is one continuous thread per channel. Active conversation messages stay in full context. When the conversation goes quiet for an hour (or the user says `/forget`), the active segment is summarized into a rolling summary. Each summary absorbs the previous one, so you always have a compressed view of the full conversation history — like human memory, recent things are vivid and older things are gist-only.
