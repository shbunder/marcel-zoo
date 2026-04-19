---
name: jobs
description: Create and manage background jobs (scheduled tasks, monitors, digests)
---

# Background Jobs

You can create background jobs that run automatically on schedules or in response to events. Jobs execute as headless agent turns with their own system prompt and task — they have access to all integration skills.

## Templates

Use `job_templates` to see available templates. Pick the right one based on the user's request:

| Template | Use when | Default trigger |
|----------|----------|----------------|
| **sync** | User wants to periodically fetch/sync data | interval (8h) |
| **check** | User wants to monitor a condition and get alerted | event (after another job) |
| **scrape** | User wants to fetch content from websites | interval (1h) |
| **digest** | User wants a periodic summary message | cron (daily at 7:00) |

## Trigger types

Choose the trigger type based on the user's language:

- **cron** — "every morning at 7", "every Monday", "at midnight" → use cron expressions
- **interval** — "every 8 hours", "every 30 minutes" → use interval_hours
- **event** — "after the bank sync", "when scraping is done" → use after_job with the triggering job's ID
- **oneshot** — "run this once", "do it now" → runs once then disables itself

## Common cron expressions

| Schedule | Cron |
|----------|------|
| Every day at 7:00 | `0 7 * * *` |
| Every day at 8:00 and 20:00 | `0 8,20 * * *` |
| Every Monday at 9:00 | `0 9 * * 1` |
| Every hour | `0 * * * *` |
| Every 6 hours | `0 */6 * * *` |

## Creating a job

1. Understand what the user wants to automate
2. Pick the right template (or use custom system_prompt)
3. Determine the trigger type and schedule
4. **Always confirm the configuration with the user before creating**
5. Call `create_job` with all parameters

## Example: bank balance check after sync

```
create_job(
    name="Low balance alert",
    task="Call banking.balance. If any account balance is below 100 EUR, notify the user with a warning including the account name and current balance. If all balances are fine, produce no output.",
    trigger_type="event",
    after_job="<bank-sync-job-id>",
    system_prompt="You are a monitoring worker. Check bank balances and only alert if a condition is met. Be concise.",
    template="check",
    notify="on_output",
    skills=["banking.balance"]
)
```

## Example: morning digest

```
create_job(
    name="Good morning digest",
    task="Compose a good morning message. Include: 1) Today's calendar events (use icloud.calendar), 2) Important reminders. Be warm and concise. Send via marcel(action='notify').",
    trigger_type="cron",
    cron="0 7 * * *",
    system_prompt="You are Marcel's morning digest composer. Gather information and compose a single, well-formatted morning message. Use marcel(action='notify', message='...') to send it.",
    template="digest",
    model="anthropic:claude-sonnet-4-6",
    notify="always",
    skills=["icloud.calendar"]
)
```

## Managing jobs

- `list_jobs` — show all jobs with status and next run time
- `get_job(job_id)` — detailed view with recent run history
- `update_job(job_id, ...)` — change schedule, prompt, status, etc.
- `delete_job(job_id)` — remove a job entirely
- `run_job_now(job_id)` — trigger immediate execution

## Tips

- Use `anthropic:claude-haiku-4-5-20251001` for simple tasks (sync, check) to minimize cost
- Use `anthropic:claude-sonnet-4-6` for tasks requiring reasoning (digests, summaries)
- Any pydantic-ai-supported model works — e.g. `openai:gpt-4o-mini` for cheap reasoning
- Jobs with `notify: "on_output"` only message the user when there's something to say — ideal for monitors
- Combine related tasks into a single digest job rather than chaining many small ones
