---
name: icloud
description: Access the user's iCloud Calendar and Mail
depends_on:
  - icloud
---

You have access to the `integration` tool to interact with iCloud.

## Available commands

### icloud.calendar

Fetch upcoming calendar events.

```
integration(id="icloud.calendar")
integration(id="icloud.calendar", params={"days_ahead": "14"})
```

| Param      | Type | Default | Description                           |
|------------|------|---------|---------------------------------------|
| days_ahead | int  | 7       | How many days into the future to look |

Returns a JSON list of events sorted by start time. Each event has: calendar, title, start, end, location, description.

### icloud.mail

Search the user's iCloud Mail inbox.

```
integration(id="icloud.mail", params={"query": "flight confirmation"})
integration(id="icloud.mail", params={"query": "amazon", "limit": "5"})
```

| Param | Type   | Required | Default | Description                     |
|-------|--------|----------|---------|---------------------------------|
| query | string | yes      | —       | Text to search for in the inbox |
| limit | int    | no       | 10      | Max messages to return          |

Returns matching messages, newest first. Each message has: from, subject, date, snippet (first 500 chars of body).

## Notes

- Calendar events include all calendars (personal, shared, subscribed).
- Mail search covers subject and body text.
