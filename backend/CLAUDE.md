# backend/CLAUDE.md

Context for AI agents working inside the `backend/` directory of L-ESCROW.

## What this directory contains

All server-side code: FastAPI application, SQLite database layer, Jinja2 templates, and static assets. The entry point is `backend/app.py`. Run from the repo root with `uvicorn backend.app:app --reload`.

---

## app.py — Route Map

All routes are registered in `backend/app.py`. No route files or routers — everything is in one file.

### Page routes (Jinja2 templates)

| Route | Template | Purpose |
|---|---|---|
| `GET /` | `dashboard.html` | Wallet status, balance card, active pacts feed |
| `GET /settings` | `settings.html` | Mandate form — buyer key, merchant key, budgets |
| `GET /marketplace` | `marketplace.html` | Live RFP bulletin board with bids |

### API routes

| Route | Auth | Description |
|---|---|---|
| `POST /api/v1/mandate` | — | Save buyer + merchant Locus keys, validate both against `/pay/balance` |
| `GET /api/v1/balance` | — | Proxy buyer wallet balance from Locus |
| `POST /api/v1/rfp` | — | Create new RFP (Open status) |
| `POST /api/v1/bid` | — | Submit bid; triggers full Locus Checkout flow if within budget |
| `GET /api/v1/rfps` | — | List RFPs, optional `?status=` filter |
| `GET /api/v1/rfps/{rfp_id}/bids` | — | List bids for one RFP |
| `POST /api/v1/webhook/locus` | HMAC | Locus event receiver — `checkout.session.paid` |
| `GET /api/v1/debug/payment/{tx_id}` | — | Dev tool — inspect Locus transaction |

**Not yet built**: `POST /api/v1/verify` — Assessor PASS/FAIL endpoint.

---

## Locus Checkout Flow (inside `POST /api/v1/bid`)

This is the most complex part of the codebase. Understand this before touching it.

### Two Locus accounts
- `locus_auth_token` — **buyer** account; pays sessions autonomously
- `merchant_locus_token` — **merchant** account; creates sessions, receives payment

Both are stored in the `owner` table (id=1) and set via `POST /api/v1/mandate`.

### Step-by-step on every qualifying bid

A bid qualifies for auto-payment when `bid_amount <= rfp.max_budget` and both tokens are configured.

```
1. POST /api/checkout/sessions          (merchant token)
        → session_id, webhookSecret, checkoutUrl

2. db.set_rfp_verifying(rfp_id, session_id, webhookSecret, bid_id)
        → RFP status: Open → Verifying

3. POST /checkout/agent/pay/{sessionId} (buyer token)
        body: {"payerEmail": seller_email}
        → transaction_id (stored but not used for polling)

4. BackgroundTask: _poll_and_confirm()
        loop 30× (2s sleep each = 60s max):
            GET /checkout/sessions/{sessionId}  (merchant token)
            data.status == "PAID"   → db.accept_bid()   → RFP: Locked
            data.status == "EXPIRED"|"CANCELLED" → db.revert_rfp_to_open()
        timeout after 60s → db.revert_rfp_to_open()
```

### Critical gotchas
- `checkoutUrl` is extracted from the session creation response — **never constructed manually**. The beta checkout domain (`checkout.beta.paywithlocus.com`) does not resolve.
- **Do not poll** `GET /checkout/agent/payments/{transactionId}` — returns 403 for cross-account transactions. Always poll the session endpoint instead.
- `db.set_rfp_verifying()` is called **before** the pay call so the DB is consistent even if the server crashes mid-flight.

---

## database/db.py — Function Reference

### Owner / Policy
| Function | Description |
|---|---|
| `init_db()` | Create all tables, run migrations, seed id=1 rows |
| `get_owner() -> dict` | Single-row owner record |
| `update_mandate(token, merchant_token, max_budget, daily_limit)` | Persist both Locus keys |
| `get_policy() -> dict` | Single-row policy record |
| `update_policy(required_assessor_score, allowed_service_types)` | Update policy |

### RFPs
| Function | Description |
|---|---|
| `create_rfp(id, buyer_id, task_spec, max_budget, deadline_seconds, min_reputation, verification_type)` | Insert new RFP |
| `get_rfps(status=None) -> list[dict]` | All RFPs, optional status filter |
| `get_rfp(rfp_id) -> dict\|None` | Single RFP by id |
| `get_rfp_by_session(session_id) -> dict\|None` | Webhook lookup by Locus session id |
| `set_rfp_verifying(rfp_id, session_id, webhook_secret, bid_id)` | Transition to Verifying |
| `revert_rfp_to_open(rfp_id)` | Rollback on payment failure — clears session, resets bid to Pending |

### Bids
| Function | Description |
|---|---|
| `create_bid(id, rfp_id, seller_id, seller_email, bid_amount, eta_seconds)` | Insert new bid |
| `get_bids_for_rfp(rfp_id) -> list[dict]` | All bids for an RFP |
| `accept_bid(bid_id, rfp_id, session_id, transaction_id)` | Atomic: RFP→Locked, bid→Accepted, rest→Rejected |

### Database schema

**`owner`** (id=1 always):
- `locus_auth_token TEXT` — buyer Locus API key
- `merchant_locus_token TEXT` — merchant Locus API key
- `max_task_budget REAL`
- `daily_limit REAL`

**`agent_policies`** (id=1 always):
- `required_assessor_score REAL DEFAULT 4.5`
- `allowed_service_types TEXT` — JSON array

**`rfps`**:
- `id TEXT PRIMARY KEY` — UUID
- `buyer_id TEXT`, `task_spec TEXT`, `max_budget REAL`, `currency TEXT DEFAULT 'USDC'`
- `deadline_seconds INTEGER`, `min_reputation REAL`, `verification_type TEXT`
- `status TEXT DEFAULT 'Open'` — Open | Verifying | Locked | Completed | Disputed
- `escrow_session_id TEXT` — Locus session id (set during Verifying)
- `webhook_secret TEXT` — HMAC secret for webhook verification
- `verifying_bid_id TEXT` — bid currently in flight (cleared after accept/revert)
- `created_at TIMESTAMP`

**`bids`**:
- `id TEXT PRIMARY KEY` — UUID
- `rfp_id TEXT` — FK to rfps
- `seller_id TEXT`, `seller_email TEXT`, `bid_amount REAL`, `eta_seconds INTEGER`
- `status TEXT DEFAULT 'Pending'` — Pending | Accepted | Rejected
- `locus_transaction_id TEXT` — from pay response
- `created_at TIMESTAMP`

---

## templates/ — Template Notes

All templates extend `base.html`. Tailwind CSS loaded from CDN. Custom status colors from `/static/css/dashboard.css`.

| Template | Key variables passed |
|---|---|
| `base.html` | Nav: Dashboard / Marketplace / Settings. Loads `locus-integration.js`. |
| `dashboard.html` | `wallet_connected`, `owner`, `policy` |
| `settings.html` | `owner`, `policy` — form pre-fills from DB values |
| `marketplace.html` | `rfps_with_bids` — list of `{rfp: dict, bids: list[dict]}` |

`marketplace.html` has `data-refresh="true"` on the outer `<div>` — `locus-integration.js` detects this and calls `location.reload()` every 10 seconds.

Status badges use `badge-{status|lower}` CSS class (e.g. `badge-verifying`, `badge-locked`).

---

## static/ — JS and CSS

### `js/locus-integration.js`
- `showToast(message, type)` — bottom-right toast notification
- `refreshBalance()` — fetches `/api/v1/balance`, updates `#balance-display` and `#wallet-address`
- `submitMandate(event)` — form submit handler for `#mandate-form` in settings
- `pollMarketplace()` — reloads page if `[data-refresh]` element exists (marketplace only)
- Auto-wired on `DOMContentLoaded`: mandate form submit, 30s balance poll, 10s marketplace reload

### `css/dashboard.css`
- CSS custom properties for all 5 escrow states
- `.badge-*` and `.status-*` classes consuming those properties
- `.toast` + `.toast.show` animation classes

---

## What is NOT yet built

- **`POST /api/v1/verify`** — Assessor submits PASS/FAIL verdict
  - PASS: call Locus to release funds to seller, set RFP → Completed
  - FAIL: call Locus to cancel/refund, set RFP → Disputed
- **Dashboard pacts feed** — currently shows static empty state; needs to pull from `rfps` table
- **Agent authentication** — all endpoints are open; JWT / wallet-signature auth is planned
- **Reputation gating** — `min_reputation` stored in RFP but not enforced on bid submission
- **Assessor rotation** — no assignment logic yet; any agent can call verify
