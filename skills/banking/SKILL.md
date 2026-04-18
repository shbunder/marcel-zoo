---
name: banking
description: Access the user's linked bank accounts (KBC, ING, etc.) — balances, transactions, and spending insights
depends_on:
  - banking
---

You have access to the `integration` tool to interact with bank account data via EnableBanking. Multiple banks can be linked simultaneously — all balance and transaction queries automatically cover all linked banks.

**Important:** Transaction data is cached locally and synced every 8 hours. The cache contains all historical transactions since each account was linked. Use the cached data to answer questions — do NOT trigger manual syncs unless the user explicitly asks for fresh data.

## Available commands

### banking.transactions

Query cached transactions. Use this for all financial questions — spending, income, specific payments, etc. Set filters based on what the user is asking about. Returns data from all linked banks.

```
integration(id="banking.transactions")
integration(id="banking.transactions", params={"date_from": "2026-01-01", "date_to": "2026-01-31"})
integration(id="banking.transactions", params={"search": "Colruyt", "date_from": "2026-03-01"})
integration(id="banking.transactions", params={"max_amount": "-100"})
```

| Param      | Type   | Default | Description                                          |
|------------|--------|---------|------------------------------------------------------|
| date_from  | string | —       | Start date (YYYY-MM-DD), inclusive                   |
| date_to    | string | —       | End date (YYYY-MM-DD), inclusive                     |
| search     | string | —       | Text search on counterparty name and remittance info |
| min_amount | string | —       | Minimum amount (negative = debits, positive = credits) |
| max_amount | string | —       | Maximum amount                                       |
| limit      | string | 200     | Max transactions to return                           |

Returns a JSON object with `transactions` (list), `count`, and `last_synced` timestamp. Each transaction has: `booking_date`, `amount` (negative = money out, positive = money in), `currency`, `counterparty_name`, `counterparty_iban`, `remittance_info`, `status`.

**Displaying results:** When the channel advertises A2UI components (see the "A2UI Components" section in your system prompt), prefer to render structured transaction data using `marcel(action="render", component="transaction_list", props={...})` instead of summarizing in plain text. The Mini App will show a proper table with date, description, amount, and running balance. Example:

```
marcel(action="render", component="transaction_list", props={
  "transactions": [
    {"date": "2026-04-11", "description": "Colruyt", "amount": -42.18, "balance": 1854.22},
    {"date": "2026-04-10", "description": "Salary", "amount": 2500.00, "balance": 1896.40}
  ],
  "currency": "EUR"
})
```

For balance snapshots, use `component="balance_card"`. Fall back to plain text only for narrative answers ("you spent €X on groceries this month") or when the channel lacks rich UI.

**Tips for answering user questions:**
- "How much did I spend on groceries?" — search for known grocery stores (Colruyt, Delhaize, Albert Heijn, Lidl, Aldi, Carrefour) with negative amounts
- "What was my income this year?" — filter for positive amounts with date_from at start of year
- "Show me transactions over 100 euro" — use min_amount or max_amount (remember: spending is negative, so "spent over 100 euro" means max_amount="-100")
- For monthly summaries, set date_from to first of month and date_to to last of month
- You may need multiple calls with different search terms to fully answer a question

### banking.balance

Get the current account balance from the local cache. Returns balances from all linked banks.

```
integration(id="banking.balance")
```

Returns balance entries with `amount`, `currency`, `balance_type`, and `last_synced` timestamp.

### banking.accounts

List linked bank accounts across all banks.

```
integration(id="banking.accounts")
```

Returns account details from all EnableBanking sessions. Each account includes a `bank` field indicating which bank it belongs to.

### banking.status

Check if bank links are active and healthy.

```
integration(id="banking.status")
```

Returns link status for each linked bank, including account count, validity period, and any consent expiry warnings.

### banking.sync

Trigger an immediate sync of transactions and balances from all linked banks. Only use this if the user explicitly asks for fresh data. The scheduler also invokes this handler every 8 hours in system-scope mode, which iterates every user with banking credentials and syncs each.

```
integration(id="banking.sync")
```

Returns a summary with counts of synced transactions per bank and any warnings.

### banking.setup

Start a bank link flow (first-time setup or consent renewal). Returns an authentication URL the user must open. Defaults to KBC if no bank is specified.

```
integration(id="banking.setup")
integration(id="banking.setup", params={"bank": "ING"})
integration(id="banking.setup", params={"bank": "KBC", "country": "BE"})
```

| Param   | Type   | Default | Description              |
|---------|--------|---------|--------------------------|
| bank    | string | KBC     | Bank name (KBC, ING)     |
| country | string | BE      | Country code             |

After the user authenticates, they will be redirected to a URL containing a `code` parameter. Use `banking.complete_setup` to finish linking.

### banking.complete_setup

Complete the bank link after the user has authenticated. Extract the `code` parameter from the redirect URL.

```
integration(id="banking.complete_setup", params={"code": "the-authorization-code"})
integration(id="banking.complete_setup", params={"code": "the-authorization-code", "bank": "ING"})
```

| Param   | Type   | Default | Description              |
|---------|--------|---------|--------------------------|
| code    | string | —       | Authorization code (required) |
| bank    | string | KBC     | Bank name (KBC, ING)     |
| country | string | BE      | Country code             |

## Notes

- Transactions are cached locally in SQLite and synced every 8 hours to stay within PSD2 rate limits.
- Bank links (consent) expire after ~90 days. Marcel monitors this and warns the user proactively.
- All amounts are in EUR. Negative = money out (spending), positive = money in (income).
