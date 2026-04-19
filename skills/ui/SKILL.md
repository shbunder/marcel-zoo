---
name: ui
description: Built-in A2UI components for rich content rendering
---

Marcel's built-in UI components for rendering structured content across all platforms (Telegram Mini App, iOS, macOS).

These components are available automatically. When you want to display structured data (calendars, checklists, etc.), emit an A2UI artifact with the appropriate component name and props.

## Available Components

- **calendar** — Event list grouped by date with time and location
- **checklist** — Interactive checklist with toggleable items

## Usage

Create an artifact with `content_type: "a2ui"` and set `component_name` to one of the above. The `content` field contains the JSON-serialized props matching the component's schema.
