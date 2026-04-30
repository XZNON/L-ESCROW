# Spec: Agent UI

## Overview

This feature adds a live `/agents` page that makes the 15-agent population visible in the browser. Each agent is displayed as a card showing its tier, current status, bids placed, bids won, and last active time — all derived from the existing `bids` and `rfps` tables with no changes to agent code. The page auto-refreshes every 10 seconds, mirroring the Marketplace pattern. This turns the terminal-only runner output into a persistent, shareable view of the agent economy.

## Depends on

- Step 03 — Agent Squad (Buyer, Seller, Assessor)
- Step 06 — Agent Population (15 agents with `assigned_seller_id` on RFPs)

## Routes

- `GET /agents` — Agents page (Jinja2 template) — public
- `GET /api/v1/agents` — JSON agent stats for auto-refresh polling — public

## Database changes

No new tables or columns.

New DB helper in `backend/database/db.py`:

```python
def get_agent_stats() -> list[dict]:
```

Single query joining `bids` and `rfps`:
- `seller_id`
- `bids_total` — COUNT of all bids placed
- `bids_won` — COUNT where `bids.status = 'Accepted'`
- `last_bid_at` — MAX(`bids.created_at`)
- `is_generating` — 1 if any Locked RFP has `assigned_seller_id = seller_id`, else 0

Query sketch:
```sql
SELECT
    b.seller_id,
    COUNT(b.id)                                          AS bids_total,
    SUM(CASE WHEN b.status = 'Accepted' THEN 1 ELSE 0 END) AS bids_won,
    MAX(b.created_at)                                    AS last_bid_at,
    EXISTS (
        SELECT 1 FROM rfps r
        WHERE r.assigned_seller_id = b.seller_id
          AND r.status = 'Locked'
    )                                                    AS is_generating
FROM bids b
GROUP BY b.seller_id
ORDER BY bids_won DESC, last_bid_at DESC
```

## Templates

- **Create:** `backend/templates/agents.html` — agent roster page
- **Modify:** `backend/templates/base.html` — add "Agents" nav link between Marketplace and Sandbox

## Files to change

- `backend/app.py` — add `GET /agents` page route and `GET /api/v1/agents` JSON route
- `backend/database/db.py` — add `get_agent_stats()` helper
- `backend/templates/base.html` — add nav link

## Files to create

- `backend/templates/agents.html`

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs — raw `sqlite3` with `?` parameterised queries only
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Tier is derived from `seller_id` format: `seller-{tier}-{nn}` → tier = middle segment. `seller-agent-01` → tier = `"legacy"`.
- Status labels (derived in Python, passed to template):
  - `"Generating"` — `is_generating = 1`
  - `"Idle"` — otherwise
- Tier badge colours map to existing CSS custom properties:
  - `intern` → `--color-escrow-open` (blue)
  - `pro` → `--color-escrow-locked` (amber)
  - `expert` → `--color-escrow-completed` (green)
  - `legacy` → `--color-escrow-verifying` (purple)
- No new CSS custom properties — map tier colours to existing escrow state variables
- Status badge reuses existing `.badge-*` classes: `badge-locked` for Generating, `badge-open` for Idle
- `last_bid_at` displayed as relative time (e.g. "3m ago") — compute in Python before passing to template, not in JS
- Auto-refresh: add `data-refresh="true"` on the outer div; `locus-integration.js` already handles 10s reload

## Definition of done

- `GET /agents` returns 200 and renders the page without error
- Nav bar shows "Agents" link on all pages
- After running agents for 30s, the page shows ≥ 1 agent card with `bids_total > 0`
- A Locked RFP with `assigned_seller_id` set causes that agent's card to show "Generating" status
- Tier badge colour differs between intern / pro / expert cards
- Page auto-refreshes every 10 seconds (verify via network tab)
- `GET /api/v1/agents` returns `{"success": true, "agents": [...]}` with correct fields
- Empty state renders cleanly when no bids exist yet
