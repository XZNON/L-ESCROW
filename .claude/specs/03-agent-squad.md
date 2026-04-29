# Spec: Agent Squad

## Overview

This feature implements the three autonomous agent personas — Buyer, Seller, and Assessor — that drive L-ESCROW's core lifecycle without human intervention. Each agent lives in `backend/agents/` as a standalone Python module. The Buyer reads the owner mandate and posts RFPs; the Seller polls for open RFPs and submits profitable bids; the Assessor is triggered when an RFP reaches `Locked` status, inspects the task spec against the delivered work, and calls `POST /api/v1/verify` with a PASS or FAIL verdict that releases or refunds the escrowed USDC. This step is the first time the system runs end-to-end without a human touching the API directly.

---

## Depends on

- Step 01: Human Command Center — `locus_auth_token` and `merchant_locus_token` must be stored in `owner` (id=1).
- Step 02: Marketplace Hub — `POST /api/v1/rfp`, `POST /api/v1/bid`, `GET /api/v1/rfps`, and `GET /api/v1/rfps/{rfp_id}/bids` must be live. RFP status lifecycle (`Open → Verifying → Locked`) must be functional.
- `POST /api/v1/verify` does **not** exist yet — it is created in this step.

---

## Routes

- `POST /api/v1/verify` — Assessor submits PASS/FAIL verdict for a Locked RFP; triggers Locus fund release (PASS) or revert/refund (FAIL) — public (agent-accessible, no auth yet)

---

## Database changes

Add to `rfps` table (via `try/except ALTER TABLE` migration in `init_db()`):

- `assessor_id TEXT` — identity of the assessor agent that verified this pact
- `assessor_verdict TEXT` — `PASS` or `FAIL`
- `verified_at TIMESTAMP` — when the verdict was submitted

Add to `bids` table (via migration):

- No changes needed.

New DB functions to add in `backend/database/db.py`:

- `complete_rfp(rfp_id, assessor_id, verdict)` — sets status to `Completed`, records assessor identity + verdict + timestamp
- `dispute_rfp(rfp_id, assessor_id, verdict)` — sets status to `Disputed`, records assessor identity + verdict + timestamp
- `get_locked_rfps() -> list[dict]` — returns all RFPs with status `Locked` (used by Assessor polling)

---

## Templates

- **Create:** none
- **Modify:** `backend/templates/dashboard.html` — replace the static empty-state pacts table with a live query of `Locked` and `Completed` RFPs from the DB (pass `active_pacts` from the route).

---

## Files to change

- `backend/app.py` — add `POST /api/v1/verify` route; update `GET /` dashboard route to pass `active_pacts`
- `backend/database/db.py` — add `complete_rfp`, `dispute_rfp`, `get_locked_rfps` functions; add DB migrations for new columns
- `backend/templates/dashboard.html` — wire up live pacts feed
- `requirements.txt` — add `langgraph`, `anthropic` if not already present

---

## Files to create

- `backend/agents/__init__.py` — empty package marker
- `backend/agents/buyer.py` — Buyer Agent: reads mandate → decides if an RFP is needed → calls `POST /api/v1/rfp`
- `backend/agents/seller.py` — Seller Agent: polls `GET /api/v1/rfps?status=Open` → scores profitability → calls `POST /api/v1/bid`
- `backend/agents/assessor.py` — Assessor Agent: polls `GET /api/v1/rfps` for `Locked` RFPs → inspects task spec vs delivery → calls `POST /api/v1/verify`
- `backend/agents/runner.py` — thin async entrypoint that runs all three agents concurrently (for dev/demo); can be invoked with `python -m backend.agents.runner`

---

## New dependencies

- `langgraph` — multi-agent graph execution
- `anthropic` — LLM calls for Assessor verification (use groq for this)

---

## Rules for implementation

- No SQLAlchemy or ORMs — raw `sqlite3` with `?` parameterised queries only.
- All DB functions live in `backend/database/db.py`; agents call the HTTP API, not the DB directly.
- Use CSS variables — never hardcode hex values in templates.
- All templates extend `base.html`.
- Agents communicate exclusively via the HTTP API (`httpx`) — they are treated as external callers, not internal modules that import `db.py` directly.
- Assessor profitability/verification logic: compare `task_spec` text against a stub `delivery_note` field (added to verify request body); use Claude Haiku via `anthropic` SDK to output a structured PASS/FAIL JSON.
- Buyer Agent posts at most one RFP per run if no `Open` RFPs exist for the configured mandate.
- Seller Agent scores a bid as profitable only if `bid_amount <= rfp.max_budget * 0.9` (10% headroom) and `eta_seconds` is within the RFP deadline.
- Assessor is stateless — it re-polls `Locked` RFPs each run; idempotent if called twice.
- `POST /api/v1/verify` must check that the target RFP is in `Locked` status before processing; return 409 otherwise.

---

## Definition of done

- [ ] `POST /api/v1/verify` with `{"rfp_id": "...", "assessor_id": "...", "verdict": "PASS", "delivery_note": "..."}` transitions a `Locked` RFP to `Completed` and the accepted bid's `locus_transaction_id` is present.
- [ ] `POST /api/v1/verify` with `verdict: "FAIL"` transitions the RFP to `Disputed`.
- [ ] `POST /api/v1/verify` on a non-`Locked` RFP returns HTTP 409.
- [ ] Dashboard (`GET /`) renders the Active Pacts table with real rows from the DB (not the static empty state).
- [ ] Running `python -m backend.agents.runner` end-to-end posts an RFP, submits a bid, and (with a mock delivery note) the Assessor calls `/api/v1/verify` and returns a verdict.
- [ ] `GET /marketplace` reflects `Completed` or `Disputed` status badge after a verify call.
- [ ] New DB columns (`assessor_id`, `assessor_verdict`, `verified_at`) exist after `init_db()` runs on an existing database.
