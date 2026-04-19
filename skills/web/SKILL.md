---
name: web
description: Search and browse the web — find information, navigate pages, read content, click, type, take screenshots
---

## How to access the web

You have three increasingly powerful (and costly) primitives. **Pick the cheapest one that does the job.**

1. **`web(action="search")`** — first resort for any information-gathering query: *"what is"*, *"latest on"*, *"current state of"*, *"who/when/where"*. Stateless, no JavaScript, fast. **Always cite the result URLs in your reply** so the user can verify.
2. **`web(action="navigate")` + `web(action="read")` / `web(action="content")` / `web(action="evaluate")`** — read a specific URL you already have, typically from a search result. Handles JavaScript. `navigate` already auto-appends a `Readable content:` block when the a11y snapshot is sparse, so one call is usually enough. Reach for `read` explicitly when you want *only* the prose or after an interaction hydrated new content.
3. **`web(action="click" / "type" / "scroll" / "press_key")`** — interactive flows: login, form filling, multi-step wizards. Stateful browser session.

**Never end a turn on a forward-looking stub** like *"let me try a different approach"* without calling a tool. If every option fails, report the failure plainly so the user can redirect you.

## The `web` tool

One tool, twelve actions, dispatched by the `action` argument — same shape as the `marcel` and `integration` tools.

### Actions

| Action | Purpose | Required args | Needs playwright |
|--------|---------|---------------|:---:|
| `search` | Search the web, return ranked results (title, URL, snippet). Rate-limited to 5/turn. | `query` | — |
| `navigate` | Open a URL, return page title + accessibility snapshot (+ readable content if sparse) | `url` | ✓ |
| `snapshot` | Re-read the current page's accessibility tree with `[ref]` numbers | — | ✓ |
| `read` | Return the current page as readable markdown prose (Trafilatura) — use on JS-heavy SPAs | — | ✓ |
| `screenshot` | Visual PNG of the current page (expensive — use only when layout matters) | — | ✓ |
| `click` | Click an element. Prefer `ref` from snapshot. | `ref` *or* `selector` *or* `x,y` | ✓ |
| `type` | Type text into an input | `text` + `ref` *or* `selector` | ✓ |
| `scroll` | Scroll up/down/left/right | `direction` | ✓ |
| `press_key` | Press a keyboard key (Enter, Escape, Tab, ArrowDown, ...) | `key` | ✓ |
| `tab` | Manage browser tabs: list, new, switch, close | `tab_action` | ✓ |
| `evaluate` | Run JavaScript in the page and return the result | `script` | ✓ |
| `content` | Get raw HTML of the page or a specific element | — | ✓ |
| `close` | Close the browser session to free resources | — | ✓ |

Actions marked ✓ need Playwright. `search` always works — in a Playwright-less environment, browser actions return `Browser error: playwright not installed` and you should fall back to `search` plus direct knowledge.

### Error contract

Every failure returns a one-line string prefixed with `Search error:` or `Browser error:`:

- `Search error: no results for "<query>". Try a broader or rephrased query.` — rephrase and retry once.
- `Search error: per-turn search limit reached (5). Summarise what you have or ask the user to narrow the query.` — stop searching, synthesise what you have.
- `Search error: Brave API key invalid or revoked` — configuration issue. Tell the user to check `BRAVE_API_KEY`.
- `Search error: Brave rate limit; DuckDuckGo fallback failed — ...` — both the primary backend (quota exhausted) and the DuckDuckGo fallback (usually bot challenge) failed in the same call. Tell the user the search backends are degraded right now. (A plain Brave rate-limit *without* this suffix never reaches you — the tool retries DDG transparently and returns those results.)
- `Search error: DuckDuckGo bot challenge — set BRAVE_API_KEY for reliable search` — DDG fallback is degraded; tell the user to configure Brave.
- `Search error: network failure — ...` — transient. Retry once; if it fails again, report plainly.
- `Browser error: ...` — see the Tips section below for recovery patterns.

## Typical workflows

### Information query ("what's the latest on X?")

```
web(action="search", query="...")           # find candidate sources
web(action="navigate", url="<best result>") # optional: read one result in full
```

Cite at least one of the result URLs in your reply.

### Reading a specific page

```
web(action="navigate", url="https://...")   # returns title + snapshot
                                            # (auto-appends Readable content on sparse/SPA pages)
# If you want prose only, or need to re-read after an interaction:
web(action="read")
# For structured data extraction, go straight to a DOM query:
web(action="evaluate", script="[...document.querySelectorAll('h2 a')].map(a => ({t: a.textContent.trim(), h: a.href}))")
```

### Interactive flow (login / form fill)

```
web(action="navigate", url="https://...")
web(action="snapshot")                      # get [ref] numbers
web(action="type", ref=2, text="user@example.com")
web(action="type", ref=3, text="secret", press_enter=True)
web(action="snapshot")                      # re-read after page change
```

### When you're done browsing

```
web(action="close")                         # free the browser session
```

## Snapshot vs Screenshot

- Use **`snapshot`** as your primary way to read and interact with pages. It returns structured text with `[ref]` numbers you can use for clicking and typing. Fast and token-efficient.
- Use **`screenshot`** when you need to see visual layout, images, CAPTCHAs, or verify appearance. Returns a PNG image. More expensive in tokens.

## Ref-based interaction

After calling `snapshot`, you get output like:

```
[1] heading "Welcome"
[2] textbox "Email" focused
[3] textbox "Password"
[4] button "Sign In"
[5] link "Forgot password?"
```

You can then `web(action="click", ref=4)` to click Sign In, or `web(action="type", ref=2, text="user@example.com")` to fill the email field.

**Important:** Refs are invalidated after any page change (navigation, form submission, AJAX update). Always re-run `snapshot` after an action that modifies the page before using refs again.

## Tips

- **Search first, browse second.** For any *"what's happening with X"* query, start with `web(action="search")`. You'll get ranked results in one round-trip. Only use `navigate` when a specific result needs full-page context.
- **Always cite result URLs.** Users need to be able to verify your claims — include at least one URL from the search results in your reply.
- **Close the session when done** with `web(action="close")` to free resources.
- **JS-heavy sites (React, Next.js, Vue).** `navigate` already handles most of them automatically: after hydration, if the a11y snapshot comes back sparse, a `Readable content:` block is appended via Trafilatura. If you need a fresh readable view after clicking/typing, call `web(action="read")`. Only reach for `evaluate` when you need *structured* data (href attributes, dataset values) rather than prose — and `content` (raw HTML) is the last-resort fallback.
- **Multi-step flows** (login, form filling): snapshot after each step to confirm the page state.
- **Navigation to private networks** (localhost, 10.x, 192.168.x, etc.) is blocked for security.
