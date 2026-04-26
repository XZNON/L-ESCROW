# Plan: Marketplace Hub and Live Monitor (Step 02)

## Context

Step 01 delivered the owner control surface (wallet connect, policy mandate). This step builds the actual marketplace: the `rfps` and `bids` SQLite tables, the five API endpoints agents use to post/query tasks and submit bids, and the `/marketplace` live bulletin board. When a bid is auto-accepted, funds are locked via Locus `POST /api/pay/send-email` (email escrow — Locus holds the USDC until claimed by the recipient, providing real on-chain escrow without needing a merchant checkout session).

---

## Critical files

- `backend/app.py` — add 5 routes
- `backend/database/db.py` — add 2 tables + 6 functions
- `backend/templates/base.html` — add Marketplace nav link
- `backend/templates/dashboard.html` — link pacts table to `/marketplace`
- `backend/templates/marketplace.html` — **create new**
- `backend/static/js/locus-integration.js` — add `pollMarketplace()`

---

## Database changes (`backend/database/db.py`)

### New tables (add to `init_db()` executescript)

```sql
CREATE TABLE IF NOT EXISTS rfps (
    id                TEXT PRIMARY KEY,
    buyer_id          TEXT NOT NULL,
    task_spec         TEXT NOT NULL,
    max_budget        REAL NOT NULL,
    currency          TEXT DEFAULT 'USDC',
    deadline_seconds  INTEGER NOT NULL,
    min_reputation    REAL DEFAULT 0.0,
    verification_type TEXT DEFAULT 'manual',
    status            TEXT DEFAULT 'Open',
    escrow_session_id TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bids (
    id              TEXT PRIMARY KEY,
    rfp_id          TEXT NOT NULL REFERENCES rfps(id),
    seller_id       TEXT NOT NULL,
    seller_email    TEXT NOT NULL,
    bid_amount      REAL NOT NULL,
    eta_seconds     INTEGER NOT NULL,
    status          TEXT DEFAULT 'Pending',
    locus_escrow_id TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### New `db.py` functions

```python
create_rfp(id, buyer_id, task_spec, max_budget, deadline_seconds, min_reputation, verification_type)
get_rfps(status=None) -> list[dict]
get_rfp(rfp_id) -> dict | None
create_bid(id, rfp_id, seller_id, seller_email, bid_amount, eta_seconds)
get_bids_for_rfp(rfp_id) -> list[dict]
accept_bid(bid_id, rfp_id, locus_escrow_id)   # atomic transaction
```

`accept_bid` runs in a single `with _connect() as conn:` block:
1. `UPDATE rfps SET status='Locked', escrow_session_id=? WHERE id=?`
2. `UPDATE bids SET status='Accepted', locus_escrow_id=? WHERE id=?`
3. `UPDATE bids SET status='Rejected' WHERE rfp_id=? AND id != ?`

---

## New routes (`backend/app.py`)

### GET /marketplace
Reads `get_rfps()`, for each rfp attaches `get_bids_for_rfp(rfp.id)`. Renders `marketplace.html`.

### POST /api/v1/rfp
```python
class RFPRequest(BaseModel):
    buyer_id: str
    task_spec: str
    max_budget: float
    deadline_seconds: int
    min_reputation: float = 0.0
    verification_type: str = "manual"
```
- Generates `rfp_id = str(uuid.uuid4())`
- Calls `db.create_rfp(...)`
- Returns `{"success": True, "rfp_id": rfp_id}`

### POST /api/v1/bid
```python
class BidRequest(BaseModel):
    rfp_id: str
    seller_id: str
    seller_email: str
    bid_amount: float
    eta_seconds: int
```
- Fetch rfp via `db.get_rfp(rfp_id)` → 404 if missing
- If `rfp.status != "Open"` → return 409
- Generate `bid_id = str(uuid.uuid4())`
- Call `db.create_bid(...)`
- **Auto-accept if** `bid_amount <= rfp.max_budget`:
  1. Call Locus `POST /api/pay/send-email`:
     ```json
     {
       "email": seller_email,
       "amount": bid_amount,
       "memo": f"L-ESCROW pact {rfp_id}: {task_spec[:80]}",
       "expires_in_days": max(1, min(365, deadline_seconds // 86400 + 1))
     }
     ```
     Auth: `Bearer {owner.locus_auth_token}`
  2. On 200/202: extract `escrow_id` from response `data`
  3. Call `db.accept_bid(bid_id, rfp_id, escrow_id)`
  4. Return `{"success": True, "bid_id": bid_id, "accepted": True, "escrow_id": escrow_id}`
  5. On Locus error: still return bid_id but `"accepted": False, "error": "..."`
- If `bid_amount > max_budget`: return bid_id with `"accepted": False, "reason": "exceeds_budget"`

### GET /api/v1/rfps
Query param `?status=Open` (optional). Returns `{"success": True, "rfps": [...]}`.

### GET /api/v1/rfps/{rfp_id}/bids
Returns `{"success": True, "bids": [...]}`.

---

## Template changes

### `base.html` — add nav link
Insert `<a href="/marketplace">Marketplace</a>` after the Settings link.

### `dashboard.html` — link pacts table
Wrap empty-state `<td>` or future rows with a link: `<a href="/marketplace">View Marketplace →</a>`.

### `marketplace.html` — new file
- Extends `base.html`
- Two-column grid: left = RFP cards, right = bid detail panel
- Each RFP card shows: `task_spec` (truncated 80 chars), `max_budget`, `status` badge, bid count
- Status badges use `badge-{status.lower()}` class → CSS vars
- Empty state: "No RFPs yet. Agents will post tasks here."
- `data-refresh="true"` attribute on `<main>` triggers `pollMarketplace()` in JS

---

## JS change (`locus-integration.js`)

Add `pollMarketplace()`:
```javascript
async function pollMarketplace() {
  const res = await fetch("/api/v1/rfps");
  // re-render the rfp list in the DOM — simplest: location.reload()
  // to avoid full complexity: just reload the page
  if (document.querySelector("[data-refresh]")) {
    location.reload();
  }
}
// Call every 10s on marketplace page
if (document.querySelector("[data-refresh]")) {
  setInterval(pollMarketplace, 10000);
}
```

---

## Verification

1. `uvicorn backend.app:app --reload`
2. `GET /marketplace` — renders empty state, no errors
3. `POST /api/v1/rfp` (curl/httpie) — returns `rfp_id`, confirm row in DB
4. `GET /api/v1/rfps` — RFP appears in list
5. `POST /api/v1/bid` with `bid_amount <= max_budget` — returns `accepted: true`, `escrow_id`; rfp status → `Locked` in DB; Locus send-email queued
6. `POST /api/v1/bid` on Locked RFP — returns 409
7. `GET /marketplace` — shows the RFP card with `Locked` badge and bid count
8. Wait 10s — page auto-reloads and reflects any new state
