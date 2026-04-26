# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: L-ESCROW

A decentralized RFP (Request for Proposal) engine enabling Agent-to-Agent (A2A) price negotiation and automated escrow settlement. AI agents bid on tasks; funds are locked via Locus SDK (USDC on Base) and released only when an independent Assessor Agent programmatically verifies the work.

## Tech Stack

- **Frontend**: Jinja2 server-side templates + Tailwind CSS CDN (MVP); React planned for later phases
- **Backend**: FastAPI (Python) — `backend/app.py` is the app entry point
- **AI Agents**: LangGraph (planned) for multi-agent coordination
- **Payments**: Locus SDK — REST API at `https://beta-api.paywithlocus.com/api`, auth via `Bearer claw_…` key
- **Database**: SQLite (`lescrow.db`, no ORM) for MVP
- **HTTP client**: `httpx` (async) for all outbound Locus API calls

## Architecture

```
[ React Frontend ] <--> [ Marketplace Hub (FastAPI) ]
      |                         ^             ^
      v                         |             |
[ Locus SDK/Web ] <-----------> [ Agent Squad ]
      |                         | (Strategist, Seller, Assessor)
      v                         v
[ Base Blockchain ] <-----> [ External Tools/APIs ]
```

**Core flow**: Human sets budget → Buyer Agent posts RFP → Seller Agent bids → Locus locks USDC in escrow → Seller delivers work → Assessor Agent verifies → Locus releases funds (or refunds on failure).

## Agent Roles

- **Strategist Agent**: Decomposes human goals using Chain-of-Thought; queries historical price DB to cap bids; uses smaller models (Llama 3 8B).
- **Seller Agent**: Scans Hub for RFPs, calculates cost + margin, submits bids.
- **Assessor Agent**: Sandboxed; no spending power, only webhook signing power to trigger PASS/FAIL. Uses GPT-4o or Claude for high-value verification. Randomly rotated to prevent collusion.

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
├── app.py              # FastAPI app — all routes registered here
├── database/db.py      # SQLite helpers: init_db, get_owner, update_mandate, get_policy, update_policy
├── templates/          # Jinja2 templates (all extend base.html)
│   ├── base.html
│   ├── dashboard.html
│   └── settings.html
└── static/
    ├── css/dashboard.css         # CSS custom properties for escrow status colors
    └── js/locus-integration.js   # fetch wrappers: submitMandate, refreshBalance
lescrow.db              # SQLite DB (auto-created on first run)
requirements.txt
```

## Database Rules

- **No ORM** — use raw `sqlite3` with `?` parameterized queries only.
- Single-row pattern: `owner` and `agent_policies` tables always use `id = 1`.
- All DB functions live in `backend/database/db.py`.

## Implemented API Endpoints

- `GET /` — Dashboard (wallet status, balance, pacts feed)
- `GET /settings` — Mandate configuration form
- `POST /api/v1/mandate` — Validates Locus API key against `/pay/balance`, then persists token + policy
- `GET /api/v1/balance` — Proxies balance from Locus API using stored token

## Marketplace Hub Frontend

- **Route**: `GET /marketplace` — A live view of the "Bulletin Board."
- **Function**: Displays `Open` RFPs and active `Bids`.
- **Visuals**: High-contrast status badges: `Bidding`, `Escrow Locked`, `Verifying`, `Settled`.

**Planned endpoints** (not yet built):

Auth: Bearer Token (JWT) for agents; Wallet Signature for humans.

- `POST /api/v1/rfp` — Buyer posts a task with `task_spec`, `max_budget`, `deadline_seconds`, `min_reputation`, `verification_type`
- `POST /api/v1/bid` — Seller bids on an RFP with `rfp_id`, `bid_amount`, `eta_seconds`
- `POST /api/v1/verify` — Assessor submits PASS/FAIL; Hub triggers Locus capture or cancellation

## Database Schema

**`owner`** (single row, id=1): `locus_auth_token` (Text), `max_task_budget` (Real), `daily_limit` (Real)

**`agent_policies`** (single row, id=1): `required_assessor_score` (Real), `allowed_service_types` (JSON text)

**Planned tables:**

**`agents`**: `id` (UUID), `wallet_address`, `reputation_score`, `type` (Buyer/Seller/Assessor)

**`pacts`** (the RFP record): `id`, `buyer_id`, `seller_id`, `status` (Open → Locked → Completed/Disputed), `escrow_session_id` (Locus ID), `task_payload` (JSON)

**`bids`**: `id` (UUID), `rfp_id` (FK), `seller_id` (UUID), `amount` (Real), `eta` (Integer), `status` (Pending/Accepted/Rejected)

## Payment State Machine

`PAYMENT_PENDING` (bid accepted, Locus session created) → Assessor verifies → `SUCCESS` (funds released to Seller) or `FAIL` (Locus session cancelled, funds refunded to Buyer).

Locus events: `checkout.session.created` to initiate, `payment_intent.succeeded` webhook to confirm.

## Locus SDK Integration

- **API base**: `https://beta-api.paywithlocus.com/api`
- **Auth**: `Authorization: Bearer <claw_…key>` on every request
- **Balance**: `GET /pay/balance` → `{data: {balance, wallet_address}}`
- **Checkout session payment**: `POST /checkout/agent/pay/:sessionId`; poll `GET /checkout/agent/payments/:transactionId` every 2s
- **Webhook event**: `checkout.session.paid` — verify with HMAC-SHA256 using `webhookSecret`
- **Policy errors**: `403` = limit exceeded; `202` = pending human approval (includes `approval_url`)
- Full SDK docs: `C:\Users\XZNON\.locus\skills`

## Security Constraints

- Agents use Shared Payment Tokens — never store private keys.
- Sellers must stake a small USDC amount to bid (Sybil resistance).
- Funds move Buyer → Smart Contract → Seller; L-ESCROW never holds keys (non-custodial).
- High-value tasks use multi-model consensus for Assessor verification.

## Success Criteria (MVP)

- Request-to-Payout under 60 seconds.
- Automated refund on Assessor rejection.
- Average transaction fee < $0.05 (excluding agent compute).
