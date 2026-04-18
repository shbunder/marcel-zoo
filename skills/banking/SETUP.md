---
name: banking
description: Guide the user through setting up bank account access via EnableBanking
---

The user is asking about banking, but bank integration is **not yet configured** for their account.

## How to set up banking

Marcel uses EnableBanking (PSD2) to securely access bank accounts. Before linking any bank, the system needs:

1. **EnableBanking App ID** — a developer credential from [enablebanking.com](https://enablebanking.com)
2. **Private key** (`enablebanking.pem`) — the corresponding signing key

These are system-level credentials (not per-user). If they're missing, an administrator needs to set them up first.

### Once EnableBanking is configured

The user can link their bank account by saying:

- "Set up KBC banking" (or ING, or any supported Belgian bank)

Marcel will generate an authentication URL. The user opens it in their browser, logs in to their bank, and authorizes access. Marcel then stores the link and starts syncing transactions automatically.

### Supported banks

- KBC (Belgium)
- ING (Belgium)

### What becomes available after setup

- **Balances** — current account balances across all linked banks
- **Transactions** — full history with search, date filters, and amount filters
- **Spending insights** — Marcel can analyze spending patterns, categorize expenses
- **Multi-bank** — multiple banks can be linked simultaneously

Tell the user what's needed and offer to help them through the linking process once the system credentials are in place.
