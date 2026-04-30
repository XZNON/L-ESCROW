# Spec: Agent Population

## Overview

This feature scales the Seller side from a single `seller-agent-01` to a diverse population of 15 agents across three tiers (Intern, Pro, Expert). Each tier has distinct bid probability, minimum bounty threshold, poll cadence, and identity. To keep LLM costs near zero, bidding uses pure Python logic (Phase A / $0); only the winning Seller Agent calls Groq for code generation (Phase C / ~$0.01). The runner spawns all 15 agents concurrently alongside the existing Buyer and Assessor.

## Depends on

- Step 01 — Core Hub + Locus Checkout
- Step 02 — Marketplace UI
- Step 03 — Agent Squad (Buyer, Seller, Assessor)
- Step 04 — Multi-Model Consensus
- Step 05 — Simulation Sandbox

## Routes

No new routes.

## Database changes

Add `assigned_seller_id TEXT` column to `rfps` — written by `db.accept_bid()` so the winning Seller Agent can detect its own Locked RFPs. Migration via `try/except ALTER TABLE` in `init_db()`.

## Templates

- **Modify:** `backend/templates/marketplace.html` — show `assigned_seller_id` (tier badge) on Locked RFP cards so the viewer can identify which agent won.

## Files to change

- `backend/agents/seller.py` — refactor into a `SellerAgent` class parameterised by tier config; expose `build_seller_graph()` and `run_seller()` at module level for backward compat; add `assigned_seller_id` detection so only the winning agent calls `_generate_fix`.
- `backend/agents/runner.py` — replace single `run_seller` call with factory that spawns 15 agents; print tier summary on startup.
- `backend/database/db.py` — add `assigned_seller_id` column migration; update `accept_bid()` to write the winning `seller_id`; add `get_locked_rfps_for_seller(seller_id)` helper.
- `backend/templates/marketplace.html` — render `assigned_seller_id` badge on Locked cards.

## Files to create

- `backend/agents/seller_population.py` — tier definitions, `AGENT_POPULATION` list, `make_seller_agents()` factory returning list of `(coroutine, label)` tuples ready for `asyncio.gather()`.

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs — raw `sqlite3` with `?` parameterised queries only.
- Use CSS variables — never hardcode hex values.
- All templates extend `base.html`.
- **Lazy Generation**: bidding nodes must never call Groq. Only the `submit_bids` node of the winning agent (detected via `rfp.assigned_seller_id == self.seller_id` on a `Locked` RFP) may call `_generate_fix`.
- **No duplicate bids**: each agent checks existing bids for its own `seller_id` before submitting — existing logic must be preserved per agent identity.
- **Tier filtering in score_rfps**: Intern bids on everything ≥ $0, Pro only ≥ $20, Expert only ≥ $45. Check `rfp["max_budget"]` against `min_bounty`.
- **Bid probability**: apply per-tier probability with `random.random() < bid_probability` before submitting — agents sometimes pass on eligible RFPs.
- **Poll intervals**: Intern 5–8 s (random per instance), Pro 10–15 s, Expert 20–30 s. Randomise once at instantiation.
- **seller_id format**: `seller-{tier}-{index:02d}` e.g. `seller-intern-01`, `seller-pro-03`, `seller-expert-05`.
- `runner.py` must still launch the existing single Buyer and single Assessor alongside the 15 Sellers.
- Keep `SELLER_ID = "seller-agent-01"` constant in `seller.py` for backward compatibility with existing demo/test data; new agents use ids from the population module.

## Definition of done

- `python -m backend.agents.runner` starts without error and prints 15 seller agent labels in the startup summary.
- Marketplace shows multiple bids from different `seller-intern-*`, `seller-pro-*`, `seller-expert-*` agents on a single Open RFP after ~30 seconds.
- Only one bid transitions the RFP to Verifying/Locked; the winning agent's `seller_id` is stored in `rfps.assigned_seller_id`.
- No PR file (`prs/pr_*.py`) is written by a non-winning agent for a sandbox RFP.
- Locked RFP cards in marketplace display the winning agent's `assigned_seller_id`.
- Expert agents do not bid on RFPs with `max_budget < 45`.
- Pro agents do not bid on RFPs with `max_budget < 20`.
- `GET /api/v1/rfps/{rfp_id}/bids` returns ≥ 3 bids for a typical $50+ RFP.
