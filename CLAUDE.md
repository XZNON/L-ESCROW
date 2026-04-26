# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: L-ESCROW

A decentralized RFP (Request for Proposal) engine enabling Agent-to-Agent (A2A) price negotiation and automated escrow settlement. AI agents bid on tasks; funds are locked via Locus Checkout (USDC on Base) and released only when an independent Assessor Agent programmatically verifies the work.

## Tech Stack

- **Frontend**: Jinja2 server-side templates + Tailwind CSS CDN (MVP); React planned for later phases
- **Backend**: FastAPI (Python) — `backend/app.py` is the single app entry point
- **AI Agents**: LangGraph (planned) for multi-agent coordination
- **Payments**: Locus SDK — REST API at `https://beta-api.paywithlocus.com/api`, auth via `Bearer claw_…` key
- **Database**: SQLite (`lescrow.db`, no ORM) for MVP
- **HTTP client**: `httpx` (async) for all outbound Locus API calls

## Architecture

```
[ Jinja2 Frontend ] <--> [ Marketplace Hub (FastAPI) ]
                                  ^             ^
                                  |             |
[ Locus Checkout ] <-----------> [ Agent Squad ]
      |                           | (Buyer, Seller, Assessor)
      v                           v
[ Base Blockchain ]          [ SQLite DB ]
```

**Core flow**: Human sets budget mandate → Buyer Agent posts RFP → Seller Agent bids → Locus Checkout locks USDC → Seller delivers work → Assessor Agent verifies → Locus releases funds (or refunds on failure).

## Agent Roles

- **Buyer Agent**: Posts RFPs with task spec, max budget, deadline, and reputation requirements.
- **Seller Agent**: Scans Hub for Open RFPs, calculates cost + margin, submits bids via `POST /api/v1/bid`.
- **Assessor Agent**: Sandboxed verifier with no spending power — only submits PASS/FAIL verdicts. Triggers fund release or refund. Randomly rotated to prevent collusion.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server (from repo root)
uvicorn backend.app:app --reload

# App available at http://localhost:8000
```

## Project Structure

```
backend/
├── app.py                        # FastAPI app — all routes
├── database/
│   └── db.py                     # All SQLite helpers
├── templates/                    # Jinja2 templates (all extend base.html)
│   ├── base.html                 # Nav: Dashboard | Marketplace | Settings
│   ├── dashboard.html            # Command center — wallet status + pacts feed
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
- `GET /` — Dashboard: wallet status card, balance, active pacts feed
- `GET /settings` — Mandate form: buyer key, merchant key, max budget, daily limit, min assessor score
- `GET /marketplace` — Live bulletin board with all RFPs and their bids

### Agent API routes
- `POST /api/v1/mandate` — Validates both Locus keys against `/pay/balance`, persists tokens + policy
- `GET /api/v1/balance` — Proxies buyer balance from Locus API using stored token
- `POST /api/v1/rfp` — Create a new RFP (Open status)
- `POST /api/v1/bid` — Submit a bid; auto-triggers Locus Checkout if bid is within budget
- `GET /api/v1/rfps` — List all RFPs, optional `?status=Open` filter
- `GET /api/v1/rfps/{rfp_id}/bids` — List all bids for a specific RFP

### Utility routes
- `GET /api/v1/debug/payment/{transaction_id}` — Inspect a Locus transaction (dev only)
- `POST /api/v1/webhook/locus` — Locus webhook receiver; HMAC-SHA256 verified; handles `checkout.session.paid`

### Not yet built
- `POST /api/v1/verify` — Assessor submits PASS/FAIL; triggers fund release or refund

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

## RFP Status Lifecycle

```
Open → Verifying → Locked → Completed
                ↘          ↘
              Open (rollback)  Disputed
```

- `Open`: accepting bids
- `Verifying`: checkout session created, payment in flight (purple badge)
- `Locked`: payment confirmed, work in progress (amber badge)
- `Completed`: Assessor PASS, funds released (green badge) — **not yet implemented**
- `Disputed`: Assessor FAIL, funds refunded (red badge) — **not yet implemented**

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
- High-value tasks should use multi-model consensus for Assessor verification.

## Success Criteria (MVP)

- Request-to-Payout under 60 seconds (current polling window: 60s max).
- Automated refund on Assessor rejection.
- Average transaction fee < $0.05 (excluding agent compute).
