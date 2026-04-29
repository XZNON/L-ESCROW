# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: L-ESCROW

A decentralized RFP (Request for Proposal) engine enabling Agent-to-Agent (A2A) price negotiation and automated escrow settlement. AI agents bid on tasks; funds are locked via Locus Checkout (USDC on Base) and released only when an independent Assessor Agent programmatically verifies the work.

## Tech Stack

- **Frontend**: Jinja2 server-side templates + Tailwind CSS CDN (MVP); React planned for later phases
- **Backend**: FastAPI (Python) — `backend/app.py` is the single app entry point
- **AI Agents**: LangGraph — three autonomous agents (Buyer, Seller, Assessor) in `backend/agents/`
- **LLM**: Groq (`llama3-8b-8192`) via the `groq` SDK — used by the Assessor for PASS/FAIL reasoning
- **Payments**: Locus SDK — REST API at `https://beta-api.paywithlocus.com/api`, auth via `Bearer claw_…` key
- **Database**: SQLite (`lescrow.db`, no ORM) for MVP
- **HTTP client**: `httpx` (async) for all outbound Locus API calls and agent-to-hub calls

## Architecture

```
[ Jinja2 Frontend ] <--> [ Marketplace Hub (FastAPI) ]
                                  ^             ^
                                  |             |
[ Locus Checkout ] <-----------> [ Agent Squad ]
      |                           | (Buyer, Seller, Assessor)
      v                           v
[ Base Blockchain ]          [ SQLite DB ]
                                  |
                              [ Groq LLM ]
                         (Assessor reasoning)
```

**Core flow**: Human sets budget mandate → Buyer Agent posts RFP → Seller Agent bids → Locus Checkout locks USDC → Seller delivers work → Assessor Agent verifies via LLM → Hub marks Completed or Disputed.

## Agent Roles

- **Buyer Agent** (`backend/agents/buyer.py`): Reads owner mandate → posts one RFP per cycle if no Open RFPs exist. LangGraph graph: `fetch_open_rfps → decide → post_rfp`.
- **Seller Agent** (`backend/agents/seller.py`): Polls Open RFPs → scores profitability at 85% of max_budget → submits bids (skips duplicates). LangGraph graph: `fetch_open_rfps → score_rfps → submit_bids`.
- **Assessor Agent** (`backend/agents/assessor.py`): Polls Locked RFPs → calls Groq LLM to compare task spec vs delivery note → submits PASS/FAIL to `/api/v1/verify`. LangGraph ReAct graph: `fetch_locked_rfps → pick_next → reason → submit_verdict → pick_next (loop)`.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server (from repo root)
uvicorn backend.app:app --reload

# Run all three agents concurrently (requires server running + GROQ_API_KEY set)
python -m backend.agents.runner

# App available at http://localhost:8000
```

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes (for agents) | Groq API key for Assessor LLM calls |
| `BASE_URL` | No | Agent target URL (default: `http://localhost:8000`) |
| `SELLER_EMAIL` | No | Seller agent email (default: `seller@lescrow.dev`) |
| `FORCE_VERDICT` | No | Override Assessor verdict: `PASS` or `FAIL` (dev/demo) |

## Project Structure

```
backend/
├── app.py                        # FastAPI app — all routes
├── agents/                       # LangGraph autonomous agents
│   ├── __init__.py
│   ├── buyer.py                  # Buyer Agent — posts RFPs
│   ├── seller.py                 # Seller Agent — bids on RFPs
│   ├── assessor.py               # Assessor Agent — LLM PASS/FAIL verdict
│   └── runner.py                 # Entrypoint: python -m backend.agents.runner
├── database/
│   └── db.py                     # All SQLite helpers
├── templates/                    # Jinja2 templates (all extend base.html)
│   ├── base.html                 # Nav: Dashboard | Marketplace | Settings
│   ├── dashboard.html            # Command center — wallet status + live pacts feed
│   ├── settings.html             # Mandate config form (buyer + merchant keys)
│   └── marketplace.html          # Live bulletin board — RFP cards + bid tables
└── static/
    ├── css/dashboard.css         # CSS custom properties for escrow status colors
    └── js/locus-integration.js   # fetch wrappers + auto-refresh polling
lescrow.db                        # SQLite DB (auto-created on first run)
requirements.txt
```

## Database Rules

- **No ORM** — raw `sqlite3` with `?` parameterized queries only.
- Single-row pattern: `owner` and `agent_policies` always use `id = 1`.
- All DB functions live in `backend/database/db.py`.
- Migrations via `try/except ALTER TABLE` in `init_db()` for existing databases.

## Implemented API Endpoints

### Human / UI routes
- `GET /` — Dashboard: wallet status card, balance, **live** active pacts feed (Locked/Completed/Disputed)
- `GET /settings` — Mandate form: buyer key, merchant key, max budget, daily limit, min assessor score
- `GET /marketplace` — Live bulletin board with all RFPs and their bids (auto-refreshes every 10s)

### Agent API routes
- `POST /api/v1/mandate` — Validates both Locus keys against `/pay/balance`, persists tokens + policy
- `GET /api/v1/balance` — Proxies buyer balance from Locus API using stored token
- `POST /api/v1/rfp` — Create a new RFP (Open status)
- `POST /api/v1/bid` — Submit a bid; auto-triggers Locus Checkout if bid is within budget
- `GET /api/v1/rfps` — List all RFPs, optional `?status=Open` filter
- `GET /api/v1/rfps/{rfp_id}/bids` — List all bids for a specific RFP
- `POST /api/v1/verify` — Assessor submits PASS/FAIL; PASS→Completed, FAIL→Disputed + Locus cancel attempt

### Utility routes
- `GET /api/v1/debug/payment/{transaction_id}` — Inspect a Locus transaction (dev only)
- `POST /api/v1/webhook/locus` — Locus webhook receiver; HMAC-SHA256 verified; handles `checkout.session.paid`

## Locus Checkout Integration (Implemented)

Two separate Locus accounts are required:
- **Buyer account** (`locus_auth_token`): pays checkout sessions autonomously
- **Merchant account** (`merchant_locus_token`): creates checkout sessions, receives payment

### Bid auto-payment flow (`POST /api/v1/bid`):
1. Merchant creates checkout session: `POST /api/checkout/sessions` (merchant token)
2. Extract `session_id`, `webhookSecret`, and `checkoutUrl` from response
3. Mark RFP as `Verifying` in DB (`db.set_rfp_verifying`)
4. Buyer agent pays session: `POST /checkout/agent/pay/{sessionId}` (buyer token) with `{"payerEmail": seller_email}`
5. Background task polls `GET /checkout/sessions/{sessionId}` (merchant token) every 2s up to 60s
6. On `PAID` → `db.accept_bid()` locks RFP atomically
7. On `EXPIRED`/`CANCELLED` or timeout → `db.revert_rfp_to_open()` rolls back

### Key Locus API facts:
- **API base**: `https://beta-api.paywithlocus.com/api`
- **Checkout URL**: extract `checkoutUrl` from session creation response — do NOT construct manually
- **Poll for payment confirmation**: `GET /api/checkout/sessions/{sessionId}` — check `data.status == "PAID"`
- **Do NOT use** `GET /checkout/agent/payments/{transactionId}` — returns 403 for cross-account transactions
- **Webhook verification**: HMAC-SHA256 with `webhookSecret` from session creation; header `X-Signature-256`
- **Webhook event**: `checkout.session.paid` — `X-Webhook-Event` header; `X-Session-Id` header for lookup

### Verify / settlement flow (`POST /api/v1/verify`):
- **PASS**: DB → `Completed`. No Locus call needed — funds already settled at checkout. Seller can claim via Locus SDK independently.
- **FAIL**: DB → `Disputed`. Hub attempts `POST /checkout/sessions/{session_id}/cancel` (merchant token). If unsupported by beta API, returns `"note": "manual_resolution_required"`.

## RFP Status Lifecycle

```
Open → Verifying → Locked → Completed
                ↘          ↘
              Open (rollback)  Disputed
```

- `Open`: accepting bids
- `Verifying`: checkout session created, payment in flight (purple badge)
- `Locked`: payment confirmed, work in progress (amber badge)
- `Completed`: Assessor PASS, funds released (green badge)
- `Disputed`: Assessor FAIL, Locus cancel attempted (red badge)

## CSS Status Classes

Status badges use `badge-{status|lower}` class. Colors defined as CSS custom properties in `dashboard.css`:
```css
--color-escrow-open:       #3b82f6  (blue)
--color-escrow-verifying:  #8b5cf6  (purple)
--color-escrow-locked:     #f59e0b  (amber)
--color-escrow-completed:  #10b981  (green)
--color-escrow-disputed:   #ef4444  (red)
```

## Security Constraints

- Agents use Shared Payment Tokens — never store private keys.
- Funds move Buyer → Locus Checkout → Seller; L-ESCROW never holds keys.
- `GROQ_API_KEY` must be kept in environment variables — never hardcoded or committed.

## What Is NOT Yet Built

- **Agent authentication** — all endpoints are open; JWT / wallet-signature auth is planned
- **Reputation gating** — `min_reputation` stored in RFP but not enforced on bid submission
- **Assessor rotation** — no assignment logic; any agent can call `/api/v1/verify`
- **Seller fund claim** — Seller Agent seeing `Completed` status and calling Locus SDK to claim payment

## Success Criteria (MVP)

- Request-to-Payout under 60 seconds (current polling window: 60s max).
- Automated refund on Assessor rejection.
- Average transaction fee < $0.05 (excluding agent compute).
