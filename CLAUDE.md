# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: L-ESCROW

A decentralized RFP (Request for Proposal) engine enabling Agent-to-Agent (A2A) price negotiation and automated escrow settlement. AI agents bid on tasks; funds are locked via Locus Checkout (USDC on Base) and released only when an independent Assessor "Jury" (two independent LLMs) verifies the work. Human-in-the-Loop tie-breaker resolves disagreements.

## Implementation Status

| Step | Feature                               | Branch (merged to main)   | Status  |
| ---- | ------------------------------------- | ------------------------- | ------- |
| 01   | Core Hub + Locus Checkout             | `feature/core-hub`        | ✅ Done |
| 02   | Marketplace UI                        | `feature/marketplace`     | ✅ Done |
| 03   | Agent Squad (Buyer, Seller, Assessor) | `feature/agent-squad`     | ✅ Done |
| 04   | Multi-Model Consensus + Demo Mode     | `feature/model-consensus`    | ✅ Done |
| 05   | Simulation Sandbox                    | `feature/simulation-sandbox` | ✅ Done |

All feature branches have been merged to `main` and deleted.

---

## Tech Stack

- **Frontend**: Jinja2 server-side templates + Tailwind CSS CDN (MVP); React planned for later phases
- **Backend**: FastAPI (Python) — `backend/app.py` is the single app entry point
- **AI Agents**: LangGraph — three autonomous agents (Buyer, Seller, Assessor) in `backend/agents/`
- **LLM (Judge A)**: Groq `llama-3.3-70b-versatile` — first Assessor judge
- **LLM (Judge B)**: Groq `llama-3.3-70b-versatile` — second Assessor judge (same Groq API key, same model — gemma2-9b-it deprecated)
- **Payments**: Locus SDK — REST API at `https://beta-api.paywithlocus.com/api`, auth via `Bearer claw_…` key
- **Database**: SQLite (`lescrow.db`, no ORM) for MVP
- **HTTP client**: `httpx` (async) for all outbound Locus API calls and agent-to-hub calls

## Architecture

```
[ Jinja2 Frontend ] <--> [ Marketplace Hub (FastAPI) ]
                                  ^             ^
                                  |             |
[ Locus Checkout ] <-----------> [ Agent Squad ]
      |                           | (Buyer, Seller, Assessor/Jury)
      v                           v
[ Base Blockchain ]          [ SQLite DB ]
                                  |
                         [ Groq LLM Jury ]
                    (Judge A: Llama 3.3 70B)
                    (Judge B: Gemma 2 9B)
```

**Core flow**: Human sets budget mandate → Buyer Agent posts RFP → Seller Agent bids → Locus Checkout locks USDC → Seller delivers work → Assessor Jury (two LLMs concurrently) votes → unanimous → auto-settle → disagreement → `Conflict` status → Human tie-breaker on dashboard.

---

## Agent Roles

- **Buyer Agent** (`backend/agents/buyer.py`): Reads owner mandate → posts one RFP per cycle if no Open RFPs exist. LangGraph graph: `fetch_open_rfps → decide → post_rfp`.
- **Seller Agent** (`backend/agents/seller.py`): Polls Open RFPs → scores profitability at 85% of max_budget → submits bids (skips duplicates). LangGraph graph: `fetch_open_rfps → score_rfps → submit_bids`.
- **Assessor Agent** (`backend/agents/assessor.py`): Polls Locked RFPs → calls **two Groq models concurrently** (Llama 3.3 + Gemma 2) → unanimous → submits verdict to `/api/v1/verify` → disagreement → reports conflict to `/api/v1/report-conflict`. LangGraph graph: `fetch_locked_rfps → pick_next → reason_judges → consensus → (submit_verdict | report_conflict) → pick_next (loop)`.

---

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server (from repo root)
uvicorn backend.app:app --reload

# Run dev server in Demo Mode (simulates Locus payment, creates real sessions)
DEMO_MODE=true uvicorn backend.app:app --reload

# Run all three agents concurrently (requires server running + GROQ_API_KEY set)
GROQ_API_KEY=gsk_... python -m backend.agents.runner

# App available at http://localhost:8000
```

---

## Environment Variables

| Variable          | Required         | Purpose                                                            |
| ----------------- | ---------------- | ------------------------------------------------------------------ |
| `GROQ_API_KEY`    | Yes (for agents) | Groq API key — used for both Assessor judges                       |
| `BASE_URL`        | No               | Agent target URL (default: `http://localhost:8000`)                |
| `SELLER_EMAIL`    | No               | Seller agent email (default: `seller@lescrow.dev`)                 |
| `DEMO_MODE`       | No               | Set `true` to skip real Locus agent pay and simulate PAID after 4s |
| `FORCE_VERDICT_A` | No               | Force Judge A verdict: `PASS` or `FAIL` (testing)                  |
| `FORCE_VERDICT_B` | No               | Force Judge B verdict: `PASS` or `FAIL` (testing)                  |

> **Note**: `FORCE_VERDICT` (singular) is deprecated — use `FORCE_VERDICT_A` + `FORCE_VERDICT_B`.

---

## Project Structure

```
backend/
├── app.py                        # FastAPI app — all routes
├── agents/                       # LangGraph autonomous agents
│   ├── __init__.py
│   ├── buyer.py                  # Buyer Agent — posts RFPs
│   ├── seller.py                 # Seller Agent — bids on RFPs
│   ├── assessor.py               # Assessor Agent — dual-judge LLM jury
│   └── runner.py                 # Entrypoint: python -m backend.agents.runner
├── database/
│   └── db.py                     # All SQLite helpers
├── templates/                    # Jinja2 templates (all extend base.html)
│   ├── base.html                 # Nav: Dashboard | Marketplace | Settings
│   ├── dashboard.html            # Command center — wallet status + live pacts feed + HITL conflict UI
│   ├── settings.html             # Mandate config form (buyer + merchant keys)
│   └── marketplace.html          # Live bulletin board — RFP cards + bid tables + checkout links
└── static/
    ├── css/dashboard.css         # CSS custom properties for escrow status colors (incl. Conflict)
    └── js/locus-integration.js   # fetch wrappers + auto-refresh polling
lescrow.db                        # SQLite DB (auto-created on first run)
requirements.txt
.claude/
├── plans/                        # Implementation plans
│   ├── 03_agent_squad.md
│   └── 04_multi_model_consensus.md
└── specs/                        # Feature specs
    ├── 03-agent-squad.md
    └── 04-model-consensus.md
```

---

## Database Rules

- **No ORM** — raw `sqlite3` with `?` parameterized queries only.
- Single-row pattern: `owner` and `agent_policies` always use `id = 1`.
- All DB functions live in `backend/database/db.py`.
- Migrations via `try/except ALTER TABLE` in `init_db()` for existing databases.

---

## Implemented API Endpoints

### Human / UI routes

- `GET /` — Dashboard: wallet status card, balance, live active pacts feed, Demo Mode button
- `GET /settings` — Mandate form: buyer key, merchant key, max budget, daily limit, min assessor score
- `GET /marketplace` — Live bulletin board with all RFPs and their bids (auto-refreshes every 10s)

### Agent API routes

- `POST /api/v1/mandate` — Validates both Locus keys against `/pay/balance`, persists tokens + policy
- `GET /api/v1/balance` — Proxies buyer `usdc_balance` from Locus API using stored token
- `POST /api/v1/rfp` — Create a new RFP (Open status)
- `POST /api/v1/bid` — Submit a bid; auto-triggers Locus Checkout if bid is within budget
- `GET /api/v1/rfps` — List all RFPs, optional `?status=` filter
- `GET /api/v1/rfps/{rfp_id}/bids` — List all bids for a specific RFP
- `POST /api/v1/verify` — Assessor submits unanimous verdict; PASS→Completed, FAIL→Disputed + Locus cancel
- `POST /api/v1/report-conflict` — Assessor reports split verdict (Locked→Conflict); stores both judges' reasoning
- `POST /api/v1/settle-conflict` — Human owner resolves Conflict: PASS→Completed or FAIL→Disputed + cancel

### Demo / Utility routes

- `POST /api/v1/demo/run` — (DEMO_MODE only) Creates real Locus session + RFP + bid, simulates payment in 4s
- `GET /api/v1/debug/payment/{transaction_id}` — Inspect a Locus transaction (dev only)
- `POST /api/v1/webhook/locus` — Locus webhook receiver; HMAC-SHA256 verified; handles `checkout.session.paid`

---

## Locus Checkout Integration (Implemented)

Two separate Locus accounts are required:

- **Buyer account** (`locus_auth_token`): pays checkout sessions autonomously
- **Merchant account** (`merchant_locus_token`): creates checkout sessions, receives payment

### Bid auto-payment flow (`POST /api/v1/bid`):

1. Merchant creates checkout session: `POST /api/checkout/sessions` (merchant token)
2. Extract `session_id`, `webhookSecret`, and `checkoutUrl` from response; store `checkout_url` in DB
3. Mark RFP as `Verifying` in DB (`db.set_rfp_verifying`)
4. **If DEMO_MODE**: skip agent pay, schedule `_demo_confirm` background task (marks PAID after 4s)
5. Otherwise: Buyer agent pays session: `POST /checkout/agent/pay/{sessionId}` (buyer token)
6. Background task polls `GET /checkout/sessions/{sessionId}` (merchant token) every 2s up to 60s
7. On `PAID` → `db.accept_bid()` locks RFP atomically
8. On `EXPIRED`/`CANCELLED` or timeout → `db.revert_rfp_to_open()` rolls back

### Key Locus API facts:

- **API base**: `https://beta-api.paywithlocus.com/api`
- **Checkout UI**: `https://checkout.paywithlocus.com` (not the beta domain)
- **Balance field**: `usdc_balance` — NOT `balance` or `workspace_credits`
- **Checkout URL**: extract `checkoutUrl` from session creation response — do NOT construct manually
- **Poll for payment**: `GET /api/checkout/sessions/{sessionId}` — check `data.status == "PAID"`
- **Do NOT use** `GET /checkout/agent/payments/{transactionId}` — returns 403 for cross-account
- **Webhook**: HMAC-SHA256 with `webhookSecret`; header `X-Signature-256`; event `checkout.session.paid`

### Verify / settlement flow (`POST /api/v1/verify`):

- **PASS**: DB → `Completed`. No Locus call needed — funds already settled at checkout.
- **FAIL**: DB → `Disputed`. Hub attempts `POST /checkout/sessions/{session_id}/cancel` (merchant token).

---

## RFP Status Lifecycle

```
Open → Verifying → Locked → Completed
          ↓           ↓ ↘
         Open       Disputed  Conflict → (Completed | Disputed)
      (rollback)             [Human HITL]
```

- `Open`: accepting bids (blue badge)
- `Verifying`: checkout session created, payment in flight (purple badge)
- `Locked`: payment confirmed, work in progress — Assessor Jury evaluating (amber badge)
- `Completed`: Unanimous PASS or human settled PASS, funds released (green badge)
- `Disputed`: Unanimous FAIL or human settled FAIL, Locus cancel attempted (red badge)
- `Conflict`: **NEW** — judges disagree; paused pending human tie-breaker on dashboard (purple badge)

---

## Demo Mode

Start the server with `DEMO_MODE=true` to showcase the full flow without real USDC:

- The "Run Demo Cycle" button appears on the dashboard
- Clicking it calls `POST /api/v1/demo/run`, which creates a **real Locus checkout session** (proving the integration is live) but simulates the payment step after 4s
- The real `checkout_url` is opened in a new tab so judges/audience can see the live Locus session
- The rest of the lifecycle (Locked → Assessor Jury LLM calls → Completed/Conflict) runs for real
- `checkout_url` is stored in the DB and shown as a link on marketplace cards for Verifying/Locked RFPs

---

## Multi-Model Consensus (Assessor Jury)

The Assessor no longer uses a single LLM judge. Two judges run concurrently via `asyncio.gather()`:

- **Judge A**: `llama-3.3-70b-versatile` (Groq) — `_call_groq(rfp, delivery_note)`
- **Judge B**: `llama-3.3-70b-versatile` (Groq) — `_call_gemma(rfp, delivery_note)`

Both return `(verdict, reasoning)`. The `consensus` node checks if they agree:

- **Agree → PASS**: calls `POST /api/v1/verify` with verdict=PASS → RFP transitions to Completed
- **Agree → FAIL**: calls `POST /api/v1/verify` with verdict=FAIL → RFP transitions to Disputed
- **Disagree**: calls `POST /api/v1/report-conflict` → RFP transitions to Conflict → dashboard HITL panel

Dashboard Conflict UI: purple row tint, "View & Settle" toggle button, collapsible panel showing both judges' verdicts and reasoning side-by-side, "Release Funds (PASS)" / "Refund Buyer (FAIL)" buttons.

---

## CSS Status Classes

Status badges use `badge-{status|lower}` class. Colors defined as CSS custom properties in `dashboard.css`:

```css
--color-escrow-open: #3b82f6 (blue) --color-escrow-verifying: #8b5cf6 (purple)
  --color-escrow-locked: #f59e0b (amber) --color-escrow-completed: #10b981
  (green) --color-escrow-disputed: #ef4444 (red)
  --color-escrow-conflict: #a855f7 (purple, distinct shade);
```

---

## Security Constraints

- Agents use Shared Payment Tokens — never store private keys.
- Funds move Buyer → Locus Checkout → Seller; L-ESCROW never holds keys.
- `GROQ_API_KEY` must be kept in environment variables — never hardcoded or committed.

---

## What Is NOT Yet Built

- **Agent authentication** — all endpoints are open; JWT / wallet-signature auth is planned
- **Reputation gating** — `min_reputation` stored in RFP but not enforced on bid submission
- **Assessor rotation** — no assignment logic; any agent can call `/api/v1/verify`
- **Seller fund claim** — Seller Agent detecting `Completed` status and calling Locus SDK to claim payment
- **Real USDC flow** — workspace credits on Locus beta are non-transferable; actual USDC flow requires funded wallets

---

## Success Criteria (MVP)

- Request-to-Payout under 60 seconds (current polling window: 60s max).
- Automated refund on Assessor rejection.
- Dual-judge consensus prevents single-model hallucinations from moving funds.
- Human tie-breaker available for all disputed verdicts.
- Demo Mode allows full showcase without real USDC.
