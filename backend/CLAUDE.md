# backend/CLAUDE.md

Context for AI agents working inside the `backend/` directory of L-ESCROW.

## What this directory contains

All server-side code: FastAPI application, SQLite database layer, Jinja2 templates, static assets, and LangGraph autonomous agents. The entry point is `backend/app.py`. Run from the repo root with `uvicorn backend.app:app --reload`.

---

## app.py — Route Map

All routes are registered in `backend/app.py`. No route files or routers — everything is in one file.

Key module-level constants:
```python
LOCUS_API_BASE   = "https://beta-api.paywithlocus.com/api"
CHECKOUT_BASE_URL = "https://checkout.paywithlocus.com"   # NOT the beta subdomain
DEMO_MODE        = os.getenv("DEMO_MODE", "false").lower() == "true"
```

### Page routes (Jinja2 templates)

| Route | Template | Purpose |
|---|---|---|
| `GET /` | `dashboard.html` | Wallet status, balance card, live active pacts feed, Demo Mode button |
| `GET /settings` | `settings.html` | Mandate form — buyer key, merchant key, budgets |
| `GET /marketplace` | `marketplace.html` | Live RFP bulletin board with bids and checkout links (auto-refreshes 10s) |

### API routes

| Route | Auth | Description |
|---|---|---|
| `POST /api/v1/mandate` | — | Save buyer + merchant Locus keys, validate both against `/pay/balance` |
| `GET /api/v1/balance` | — | Proxy buyer `usdc_balance` from Locus (field name is `usdc_balance`, not `balance`) |
| `POST /api/v1/rfp` | — | Create new RFP (Open status) |
| `POST /api/v1/bid` | — | Submit bid; triggers full Locus Checkout flow (or demo confirm if DEMO_MODE) |
| `GET /api/v1/rfps` | — | List RFPs, optional `?status=` filter |
| `GET /api/v1/rfps/{rfp_id}/bids` | — | List bids for one RFP |
| `POST /api/v1/verify` | — | Assessor unanimous verdict; PASS→Completed, FAIL→Disputed + Locus cancel |
| `POST /api/v1/report-conflict` | — | Assessor split verdict (Locked→Conflict); stores both judges' reasoning |
| `POST /api/v1/settle-conflict` | — | Human owner resolves Conflict: PASS→Completed or FAIL→Disputed + cancel |
| `POST /api/v1/demo/run` | — | (DEMO_MODE only) Creates real Locus session + full RFP/bid cycle, PAID in 4s |
| `POST /api/v1/webhook/locus` | HMAC | Locus event receiver — `checkout.session.paid` |
| `GET /api/v1/debug/payment/{tx_id}` | — | Dev tool — inspect Locus transaction |

### Pydantic request models

```python
MandateRequest   # locus_auth_token, merchant_locus_token, max_task_budget, daily_limit, required_assessor_score
RFPRequest       # buyer_id, task_spec, max_budget, deadline_seconds, min_reputation, verification_type
BidRequest       # rfp_id, seller_id, seller_email, bid_amount, eta_seconds
VerifyRequest    # rfp_id, assessor_id, verdict ("PASS"|"FAIL"), delivery_note
ConflictRequest  # rfp_id, assessor_id, verdict_a, reasoning_a, verdict_b, reasoning_b
SettleRequest    # rfp_id, verdict ("PASS"|"FAIL")
```

---

## Locus Checkout Flow (inside `POST /api/v1/bid`)

This is the most complex part of the codebase. Understand this before touching it.

### Two Locus accounts
- `locus_auth_token` — **buyer** account; pays sessions autonomously
- `merchant_locus_token` — **merchant** account; creates sessions, receives payment

Both are stored in the `owner` table (id=1) and set via `POST /api/v1/mandate`.

### Step-by-step on every qualifying bid

A bid qualifies when `bid_amount <= rfp.max_budget` and both tokens are configured.

```
1. POST /api/checkout/sessions          (merchant token)
        → session_id, webhookSecret, checkoutUrl

2. db.set_rfp_verifying(rfp_id, session_id, webhookSecret, bid_id, checkout_url)
        → RFP status: Open → Verifying

3a. [DEMO_MODE] BackgroundTask: _demo_confirm() — sleep 4s → db.accept_bid()
        → RFP status: Verifying → Locked

3b. [NORMAL] POST /checkout/agent/pay/{sessionId} (buyer token)
        body: {"payerEmail": seller_email}

4.  BackgroundTask: _poll_and_confirm()
        loop 30× (2s sleep each = 60s max):
            GET /checkout/sessions/{sessionId}  (merchant token)
            data.status == "PAID"   → db.accept_bid()   → RFP: Locked
            data.status == "EXPIRED"|"CANCELLED" → db.revert_rfp_to_open()
        timeout after 60s → db.revert_rfp_to_open()
```

### Critical gotchas
- `checkoutUrl` is extracted from the session creation response — **never constructed manually**. The beta checkout domain (`checkout.beta.paywithlocus.com`) does not resolve; the correct domain is `checkout.paywithlocus.com`.
- **Do not poll** `GET /checkout/agent/payments/{transactionId}` — returns 403 for cross-account transactions. Always poll the session endpoint instead.
- `db.set_rfp_verifying()` is called **before** any pay call so the DB is consistent even if the server crashes mid-flight.
- Locus balance field is `usdc_balance` — not `balance` or `workspace_credits`. Workspace credits are non-transferable.

---

## Verify / Settlement Flow (inside `POST /api/v1/verify`)

Called by the Assessor Agent after unanimous LLM jury. Guarded: returns 409 if RFP is not `Locked`.

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

## Conflict Flow (inside `POST /api/v1/report-conflict` and `POST /api/v1/settle-conflict`)

```
report-conflict (Assessor, split verdict):
    → db.conflict_rfp(rfp_id, verdict_a, reasoning_a, verdict_b, reasoning_b)
    → RFP status: Locked → Conflict
    → Dashboard shows HITL panel with both judges' verdicts + reasoning

settle-conflict (Human owner via dashboard UI):
    → PASS: db.settle_conflict → complete_rfp → RFP: Completed
    → FAIL: db.settle_conflict → dispute_rfp → RFP: Disputed + Locus cancel attempt
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
| `set_rfp_verifying(rfp_id, session_id, webhook_secret, bid_id, checkout_url="")` | Transition to Verifying; stores checkout_url |
| `revert_rfp_to_open(rfp_id)` | Rollback on payment failure — clears session, resets bid to Pending |
| `get_locked_rfps() -> list[dict]` | All Locked RFPs — used by Assessor Agent polling |
| `get_active_pacts() -> list[dict]` | Locked/Completed/Disputed/**Conflict** RFPs joined with accepted bid — includes all judge columns |
| `complete_rfp(rfp_id, assessor_id, verdict)` | Transition → Completed, record assessor + timestamp |
| `dispute_rfp(rfp_id, assessor_id, verdict)` | Transition → Disputed, record assessor + timestamp |
| `conflict_rfp(rfp_id, verdict_a, reasoning_a, verdict_b, reasoning_b)` | **NEW** — Transition Locked → Conflict, store both judges |
| `settle_conflict(rfp_id, assessor_id, verdict)` | **NEW** — PASS delegates to complete_rfp, FAIL to dispute_rfp |

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
- `status TEXT DEFAULT 'Open'` — Open | Verifying | Locked | Completed | Disputed | **Conflict**
- `escrow_session_id TEXT` — Locus session id (set during Verifying)
- `checkout_url TEXT` — real Locus checkout URL (set during Verifying, shown on marketplace cards)
- `webhook_secret TEXT` — HMAC secret for webhook verification
- `verifying_bid_id TEXT` — bid currently in flight (cleared after accept/revert)
- `assessor_id TEXT` — identity of assessor that submitted final verdict
- `assessor_verdict TEXT` — `PASS` or `FAIL`
- `verified_at TIMESTAMP` — when verdict was submitted
- `judge_a_verdict TEXT` — **NEW** — Judge A (Llama 3.3) verdict
- `judge_a_reasoning TEXT` — **NEW** — Judge A reasoning text
- `judge_b_verdict TEXT` — **NEW** — Judge B (Gemma 2) verdict
- `judge_b_reasoning TEXT` — **NEW** — Judge B reasoning text
- `conflict_notes TEXT` — **NEW** — summary string for Conflict rows
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

### `assessor.py` — Dual-Judge Jury

**State:** `AssessorState` — `base_url`, `locked_rfps`, `current_rfp`, `delivery_note`, `verdict_a`, `reasoning_a`, `verdict_b`, `reasoning_b`, `conflict`

**Graph:**
```
fetch_locked_rfps → pick_next →(no rfp → END)
                              ↓
                         reason_judges          ← asyncio.gather(Judge A, Judge B) concurrently
                              ↓
                           consensus            ← pure logic: conflict = (verdict_a != verdict_b)
                              ↓ (conditional)
              submit_verdict ←→ report_conflict
                              ↓
                           pick_next (loop)
```

**LLM Judges:**
- **Judge A** `_call_groq(rfp, delivery_note)` — model `llama-3.3-70b-versatile`, Groq SDK
- **Judge B** `_call_gemma(rfp, delivery_note)` — model `gemma2-9b-it`, same Groq SDK/key

Both return `(verdict: str, reasoning: str)`.

**Delivery note**: `"Work completed as specified. Delivered: {task_spec} — all requirements met, tested, and ready for review."` — this phrasing consistently produces PASS verdicts in demo scenarios.

**Env vars:**
- `FORCE_VERDICT_A` — override Judge A result (`PASS`/`FAIL`)
- `FORCE_VERDICT_B` — override Judge B result (`PASS`/`FAIL`)

**`submit_verdict` node:** calls `POST /api/v1/verify` with `verdict_a` (both agree at this point)

**`report_conflict` node:** calls `POST /api/v1/report-conflict` with both verdicts + reasoning

**Entry:** `run_assessor(base_url, poll_interval=5)` — async polling loop.

---

### `runner.py`

Runs all three agents with `asyncio.gather()`. Invoke with:
```bash
GROQ_API_KEY=gsk_... python -m backend.agents.runner
```

Both Assessor judges use the same `GROQ_API_KEY`. No separate key needed for Judge B.

---

## templates/ — Template Notes

All templates extend `base.html`. Tailwind CSS loaded from CDN. Custom status colors from `/static/css/dashboard.css`.

| Template | Key variables passed |
|---|---|
| `base.html` | Nav: Dashboard / Marketplace / Settings. Loads `locus-integration.js`. |
| `dashboard.html` | `wallet_connected`, `owner`, `policy`, `active_pacts`, `demo_mode` |
| `settings.html` | `owner`, `policy` — form pre-fills from DB values |
| `marketplace.html` | `rfps_with_bids` — list of `{rfp: dict, bids: list[dict]}`, `demo_mode` |

`marketplace.html` has `data-refresh="true"` on the outer `<div>` — `locus-integration.js` detects this and calls `location.reload()` every 10 seconds. Verifying/Locked RFPs show a "View Locus Checkout Session →" link if `rfp.checkout_url` is set.

`dashboard.html` Active Pacts table has 5 columns: Task / Seller / Amount / Status / Jury. Conflict rows have purple row tint + "View & Settle" toggle button. Hidden `<tr>` beneath each Conflict row shows Judge A (Llama 3.3) and Judge B (Gemma 2) verdicts + reasoning side-by-side, with "Release Funds (PASS)" and "Refund Buyer (FAIL)" buttons.

`dashboard.html` also renders a Demo Mode amber badge and "Run Demo Cycle" button when `demo_mode=True`. Clicking the button calls `POST /api/v1/demo/run` and opens the Locus checkout URL in a new tab.

Status badges use `badge-{status|lower}` CSS class (e.g. `badge-conflict`, `badge-locked`, `badge-completed`).

---

## static/ — JS and CSS

### `js/locus-integration.js`
- `showToast(message, type)` — bottom-right toast notification
- `refreshBalance()` — fetches `/api/v1/balance`, updates `#balance-display` and `#wallet-address`
- `submitMandate(event)` — form submit handler for `#mandate-form` in settings
- `pollMarketplace()` — reloads page if `[data-refresh]` element exists (marketplace only)
- Auto-wired on `DOMContentLoaded`: mandate form submit, 30s balance poll, 10s marketplace reload

### `css/dashboard.css`
- CSS custom properties for all 6 escrow states (including `--color-escrow-conflict: #a855f7`)
- `.badge-*` and `.status-*` classes for all 6 states
- `.toast` + `.toast.show` animation classes

---

## What Is NOT Yet Built

- **Agent authentication** — all endpoints are open; JWT / wallet-signature auth is planned
- **Reputation gating** — `min_reputation` stored in RFP but not enforced on bid submission
- **Assessor rotation** — no assignment logic; any agent can call `/api/v1/verify`
- **Seller fund claim** — Seller Agent detecting `Completed` status and calling Locus SDK to claim payment
- **Real USDC flow** — Locus workspace credits (beta) are non-transferable; real USDC requires funded wallets
