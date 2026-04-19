---
name: web
description: Setup guide for the web skill — search backend + browser automation
---

## Web Skill — Setup

The `web` tool exposes twelve actions. **`search`** works out of the box with
a zero-config DuckDuckGo HTML fallback, but the rest of the actions depend
on Playwright. Configure both for the best experience.

### 1. Brave Search API (recommended)

DuckDuckGo HTML scraping is unreliable — it bot-challenges unpredictably.
Brave's free tier gives you 1000 queries/month, which is more than enough
for a household agent. If the quota is hit, Marcel falls back to
DuckDuckGo transparently.

1. Get a free API key at <https://brave.com/search/api/>
2. Add it to `.env.local`:

   ```
   BRAVE_API_KEY=your-key-here
   ```

3. Restart Marcel. `web(action="search")` will now use Brave automatically.

If `BRAVE_API_KEY` is not set, the tool falls back to DuckDuckGo HTML
scraping with a warning in the logs. The tool still works, just less
reliably.

### 2. Playwright (for browser actions)

`navigate`, `snapshot`, `click`, `type`, and the other browser actions
need Playwright installed:

```bash
# Install the playwright package
uv pip install playwright

# Install the Chromium browser binary
playwright install chromium
```

After installation, restart Marcel. The browser actions will become
available automatically — `web(action="search")` keeps working either way.

### Browser configuration (optional)

Add to `.env.local` if needed:

```
# Run in headed mode (shows browser window, useful for debugging)
BROWSER_HEADLESS=false

# Allow navigation to specific internal hosts (comma-separated)
BROWSER_URL_ALLOWLIST=*.internal.example.com,dashboard.local

# Navigation timeout in seconds (default: 30)
BROWSER_TIMEOUT=60
```

### Testing

After setup, a smoke test from any Marcel channel:

```
"What's the latest news about Paris-Roubaix?"
```

Marcel should call `web(action="search", query=...)` and cite at least one
result URL in the reply.
