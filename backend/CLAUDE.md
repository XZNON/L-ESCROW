# backend/CLAUDE.md

Context for AI agents working inside the `backend/` directory of L-ESCROW.

## What this directory contains

All server-side code: FastAPI application, SQLite database layer, Jinja2 templates, static assets, and LangGraph autonomous agents. The entry point is `backend/app.py`. Run from the repo root with `uvicorn backend.app:app --reload`.

---

## app.py — Route Map

All routes are registered in `backend/app.py`. No route files or routers — everything is in one file.

### Page routes (Jinja2 templates)

| Route | Template | Purpose |
|---|---|---|
| `GET /` | `dashboard.html` | Wallet status, balance card, live active pacts feed |
| `GET /settings` | `settings.html` | Mandate form — buyer key, merchant key, budgets |
| `GET /marketplace` | `marketplace.html` | Live RFP bulletin board with bids (auto-refreshes 10s) |

### API routes

| Route | Auth | Description |
|---|---|---|
| `POST /api/v1/mandate` | — | Save buyer + merchant Locus keys, validate both against `/pay/balance` |
| `GET /api/v1/balance` | — | Proxy buyer wallet balance from Locus |
| `POST /api/v1/rfp` | — | Create new RFP (Open status) |
| `POST /api/v1/bid` | — | Submit bid; triggers full Locus Checkout flow if within budget |
| `GET /api/v1/rfps` | — | List RFPs, optional `?status=` filter |
| `GET /api/v1/rfps/{rfp_id}/bids` | — | List bids for one RFP |
| `POST /api/v1/verify` | — | Assessor PASS/FAIL verdict; PASS→Completed, FAIL→Disputed + Locus cancel |
| `POST /api/v1/webhook/locus` | HMAC | Locus event receiver — `checkout.session.paid` |
| `GET /api/v1/debug/payment/{tx_id}` | — | Dev tool — inspect Locus transaction |

### Pydantic request models

```python
MandateRequest   # locus_auth_token, merchant_locus_token, max_task_budget, daily_limit, required_assessor_score
RFPRequest       # buyer_id, task_spec, max_budget, deadline_seconds, min_reputation, verification_type
BidRequest       # rfp_id, seller_id, seller_email, bid_amount, eta_seconds
VerifyRequest    # rfp_id, assessor_id, verdict ("PASS"|"FAIL"), delivery_note
```

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

## Verify / Settlement Flow (inside `POST /api/v1/verify`)

Called by the Assessor Agent after LLM reasoning. Guarded: returns 409 if RFP is not `Locked`.

```
PASS → db.complete_rfp(rfp_id, assessor_id, "PASS")
     → RFP status: Locked → Completed
     → No Locus call (funds already settled at checkout; seller claims independently)

FAIL → db.dispute_rfp(rfp_id, assessor_id, "FAIL")
     → RFP status: Locked → Disputed
     → Attempt POST /checkout/sessions/{session_id}/cancel (merchant token)
     → If cancel unsupported: returns {"note": "manual_resolution_required"}
```

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
| `get_locked_rfps() -> list[dict]` | All Locked RFPs — used by Assessor Agent polling |
| `get_active_pacts() -> list[dict]` | Locked/Completed/Disputed RFPs joined with accepted bid — used by dashboard |
| `complete_rfp(rfp_id, assessor_id, verdict)` | Transition Locked → Completed, record assessor + timestamp |
| `dispute_rfp(rfp_id, assessor_id, verdict)` | Transition Locked → Disputed, record assessor + timestamp |

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
- `assessor_id TEXT` — identity of assessor that submitted verdict
- `assessor_verdict TEXT` — `PASS` or `FAIL`
- `verified_at TIMESTAMP` — when verdict was submitted
- `created_at TIMESTAMP`

**`bids`**:
- `id TEXT PRIMARY KEY` — UUID
- `rfp_id TEXT` — FK to rfps
- `seller_id TEXT`, `seller_email TEXT`, `bid_amount REAL`, `eta_seconds INTEGER`
- `status TEXT DEFAULT 'Pending'` — Pending | Accepted | Rejected
- `locus_transaction_id TEXT` — from pay response
- `created_at TIMESTAMP`

---

## agents/ — LangGraph Agent Reference

All agents communicate with the Hub exclusively via HTTP (`httpx`). They never import `db.py` directly.

### `buyer.py`

**State:** `BuyerState` — `base_url`, `open_rfps`, `owner`, `should_post`, `rfp_id`

**Graph:** `fetch_open_rfps → decide →(conditional)→ post_rfp → END`

**Behaviour:** Posts at most one RFP per cycle. Only posts if no Open RFPs exist and `max_task_budget > 0`. Task spec is a hardcoded demo string for MVP.

**Entry:** `run_buyer(base_url, poll_interval=15)` — async polling loop.

---

### `seller.py`

**State:** `SellerState` — `base_url`, `open_rfps`, `profitable_rfps`, `bids_placed`

**Graph:** `fetch_open_rfps → score_rfps → submit_bids → END`

**Behaviour:** Bids at 85% of `max_budget` (15% margin). Skips RFPs already bid on by `seller-agent-01`. ETA capped at `min(deadline_seconds, 1800)`.

**Identity:** `seller_id = "seller-agent-01"`, `seller_email` from `SELLER_EMAIL` env var.

**Entry:** `run_seller(base_url, poll_interval=8)` — async polling loop.

---

### `assessor.py`

**State:** `AssessorState` — `base_url`, `locked_rfps`, `current_rfp`, `delivery_note`, `llm_reasoning`, `verdict`

**Graph:** `fetch_locked_rfps → pick_next →(conditional)→ reason → submit_verdict → pick_next (loop)`

**Behaviour (ReAct):**
1. Fetches all Locked RFPs
2. Picks first one; uses `task_spec` as delivery note for demo (auto-PASS scenario)
3. Calls Groq `llama3-8b-8192` — system prompt requests `{"verdict": "PASS"|"FAIL", "reasoning": "..."}` JSON
4. Submits verdict to `POST /api/v1/verify`
5. Loops to next Locked RFP until queue is empty

**Override:** Set `FORCE_VERDICT=FAIL` to force all verdicts to FAIL (for testing dispute flow).

**Entry:** `run_assessor(base_url, poll_interval=5)` — async polling loop.

---

### `runner.py`

Runs all three agents with `asyncio.gather()`. Invoke with:
```bash
GROQ_API_KEY=... python -m backend.agents.runner
```

---

## templates/ — Template Notes

All templates extend `base.html`. Tailwind CSS loaded from CDN. Custom status colors from `/static/css/dashboard.css`.

| Template | Key variables passed |
|---|---|
| `base.html` | Nav: Dashboard / Marketplace / Settings. Loads `locus-integration.js`. |
| `dashboard.html` | `wallet_connected`, `owner`, `policy`, `active_pacts` |
| `settings.html` | `owner`, `policy` — form pre-fills from DB values |
| `marketplace.html` | `rfps_with_bids` — list of `{rfp: dict, bids: list[dict]}` |

`marketplace.html` has `data-refresh="true"` on the outer `<div>` — `locus-integration.js` detects this and calls `location.reload()` every 10 seconds.

`dashboard.html` Active Pacts table loops over `active_pacts` (Locked/Completed/Disputed RFPs with accepted bid joined). Shows static empty state if list is empty.

Status badges use `badge-{status|lower}` CSS class (e.g. `badge-verifying`, `badge-locked`, `badge-completed`, `badge-disputed`).

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

## What Is NOT Yet Built

- **Agent authentication** — all endpoints are open; JWT / wallet-signature auth is planned
- **Reputation gating** — `min_reputation` stored in RFP but not enforced on bid submission
- **Assessor rotation** — no assignment logic; any agent can call `/api/v1/verify`
- **Seller fund claim** — Seller Agent detecting `Completed` status and calling Locus SDK to claim payment
