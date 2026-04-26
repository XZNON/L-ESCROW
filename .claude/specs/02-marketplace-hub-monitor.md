# Spec: Marketplace Hub and Live Monitor

## Overview

This feature builds the public-facing heart of L-ESCROW: a live Marketplace "Bulletin Board" where RFPs and bids are visible in real time, and a set of agent-facing API endpoints that allow Buyer Agents to post tasks and Seller Agents to submit bids. It introduces the `rfps` and `bids` tables, wires up the three core marketplace API routes, and adds a `/marketplace` page that auto-refreshes to reflect the current state of all open negotiations.

## Depends on

- Step 01 — Human Command Center (wallet connected, `owner` table exists, `locus_auth_token` stored)

---

## Routes

- `GET /marketplace` — Live bulletin board of open RFPs and active bids — (Public)
- `POST /api/v1/rfp` — Buyer Agent posts a new RFP — (Bearer JWT)
- `POST /api/v1/bid` — Seller Agent bids on an open RFP; triggers Locus escrow session creation — (Bearer JWT).If the bid is automatically accepted (or manually triggered), the backend must immediately call the Locus /checkout/agent/pay endpoint. The route should return both the bid_id and the locus_checkout_url to the caller.
- `GET /api/v1/rfps` — Returns all RFPs (optionally filtered by `status`) — (Public)
- `GET /api/v1/rfps/{rfp_id}/bids` — Returns all bids for a given RFP — (Public)

---

## Database changes

New tables (add to `init_db()` in `database/db.py`):

```sql
CREATE TABLE IF NOT EXISTS rfps (
    id               TEXT PRIMARY KEY,   -- UUID
    buyer_id         TEXT NOT NULL,
    task_spec        TEXT NOT NULL,
    max_budget       REAL NOT NULL,
    currency         TEXT DEFAULT 'USDC',
    deadline_seconds INTEGER NOT NULL,
    min_reputation   REAL DEFAULT 0.0,
    verification_type TEXT DEFAULT 'manual',
    status           TEXT DEFAULT 'Open',   -- Open | Locked | Completed | Disputed
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bids (
    id          TEXT PRIMARY KEY,   -- UUID
    rfp_id      TEXT NOT NULL REFERENCES rfps(id),
    seller_id   TEXT NOT NULL,
    bid_amount  REAL NOT NULL,
    eta_seconds INTEGER NOT NULL,
    status      TEXT DEFAULT 'Pending',  -- Pending | Accepted | Rejected
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

New `db.py` functions:

- `create_rfp(id, buyer_id, task_spec, max_budget, deadline_seconds, min_reputation, verification_type) -> None`
- `get_rfps(status=None) -> list[dict]`
- `get_rfp(rfp_id) -> dict | None`
- `create_bid(id, rfp_id, seller_id, bid_amount, eta_seconds) -> None`
- `get_bids_for_rfp(rfp_id) -> list[dict]`
- `accept_bid(bid_id, rfp_id, escrow_session_id) -> None` — sets bid status `Accepted`, rfp status `Locked`, rejects all other bids for that RFP

---

## Templates

- **Create:** `backend/templates/marketplace.html` — extends `base.html`; two-column layout: RFP cards on the left, bid list on the right. Status badges use CSS variables. Auto-refreshes every 10 seconds via `locus-integration.js`.
- **Modify:** `backend/templates/base.html` — add "Marketplace" nav link pointing to `/marketplace`.
- **Modify:** `backend/templates/dashboard.html` — link "Active Pacts" table rows to `/marketplace`.

---

## Files to change

- `backend/app.py` — register the 5 new routes above
- `backend/database/db.py` — add `rfps` and `bids` tables to `init_db()`; add the 6 new query functions
- `backend/templates/base.html` — add Marketplace nav link
- `backend/templates/dashboard.html` — link pacts table to marketplace
- `backend/static/js/locus-integration.js` — add `pollMarketplace()` function for auto-refresh

---

## Files to create

- `backend/templates/marketplace.html` — live bulletin board page

---

## New dependencies

No new dependencies.

---

## Rules for implementation

- No SQLAlchemy or ORMs.
- Parameterised queries only — all inserts/updates use `?` placeholders.
- Passwords hashed with werkzeug (if auth is extended).
- Use CSS variables — never hardcode hex values (reuse existing `--color-escrow-*` vars for status badges).
- All templates extend `base.html`.
- RFP and bid IDs are generated server-side using `uuid.uuid4()`.
- Agent auth for `POST /api/v1/rfp` and `POST /api/v1/bid` is a Bearer token validated against a simple shared secret in `owner.locus_auth_token` for the MVP (full JWT in a later step).
- `POST /api/v1/bid` must check that the RFP status is `Open` before accepting a bid; return `409` if already `Locked`.
- `accept_bid` must be atomic: update rfp, accepted bid, and rejected bids in a single transaction.
- Atomic Escrow Rule: The RFP status must never move to Locked in the database unless the Locus API successfully returns a 201 Created or 200 OK for the payment session.
- Error Handling: If the Locus API call fails (e.g., insufficient balance or network error), the database transaction must roll back, leaving the RFP Open and the bid Pending.
- Polling Logic: Add a rule that the marketplace.html UI must display a "Verifying on Chain..." state while the Locus transaction is in the 202 Accepted (pending human or network approval) state.

---

## Definition of done

- [ ] `GET /marketplace` renders without error when no RFPs exist (empty state shown).
- [ ] `POST /api/v1/rfp` with valid JSON creates a row in `rfps` and returns the new `rfp_id`.
- [ ] `GET /api/v1/rfps` returns the created RFP in the list.
- [ ] `POST /api/v1/bid` on an open RFP creates a row in `bids` and returns the new `bid_id`.
- [ ] `GET /api/v1/rfps/{rfp_id}/bids` returns the submitted bid.
- [ ] `/marketplace` page shows the RFP card and its bid after 10-second auto-refresh (or manual reload).
- [ ] Bidding on a `Locked` RFP returns HTTP `409`.
- [ ] Status badges on `/marketplace` use the correct CSS variable colours (`--color-escrow-open`, `--color-escrow-locked`).
- [ ] Handshake Verification: Successfully accepting a bid via the API returns a valid Locus Checkout URL.
- [ ] Rollback Protection: Simulating a Locus API failure (e.g., using an invalid token) prevents the RFP status from changing to Locked in the SQLite DB.

---

**Branch:** feature/marketplace-hub-monitor
**Spec file:** .claude/specs/02-marketplace-hub-monitor.md
**Title:** Marketplace Hub and Live Monitor
