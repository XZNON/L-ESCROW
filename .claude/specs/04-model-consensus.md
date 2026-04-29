# Spec: Multi-Model Consensus

## Overview

The Assessor Agent currently relies on a single Groq LLM (`llama-3.3-70b-versatile`) to decide whether to release or claw back escrow funds. A single model hallucination can trigger an incorrect payout or wrongful refund. This feature replaces the single-judge pattern with a two-judge "Jury": Judge A (Groq) and Judge B (Google Gemini Flash). Unanimous verdicts settle automatically; a disagreement transitions the RFP to a new `Conflict` status and surfaces a Human-in-the-Loop tie-breaker UI on the dashboard so the owner can manually resolve the stalemate.

## Depends on

- Step 03 — Agent Squad (Buyer, Seller, Assessor agents + `POST /api/v1/verify`)

## Routes

- `POST /api/v1/report-conflict` — Assessor signals a stalemate; transitions RFP to Conflict and stores both reasonings — public (agent-facing)
- `POST /api/v1/settle-conflict` — Human owner manually resolves a Conflict with a final verdict (`PASS` or `FAIL`) — public for MVP

## Database changes

New columns on `rfps` table (added via `try/except ALTER TABLE` migrations in `init_db()`):

| Column | Type | Purpose |
|---|---|---|
| `judge_a_verdict` | TEXT | Verdict from Judge A (Groq) |
| `judge_a_reasoning` | TEXT | One-sentence reasoning from Judge A |
| `judge_b_verdict` | TEXT | Verdict from Judge B (Gemini) |
| `judge_b_reasoning` | TEXT | One-sentence reasoning from Judge B |
| `conflict_notes` | TEXT | Summary of the disagreement |

`status` column gains a new valid value: `Conflict` (in addition to Open, Verifying, Locked, Completed, Disputed).

## Templates

- **Modify:** `backend/templates/dashboard.html`
  - Active Pacts table gains two new columns: Judge A verdict, Judge B verdict (hidden unless status is Conflict)
  - Conflict rows show a high-visibility amber/purple gradient badge
  - Each Conflict row has an expandable reasoning panel showing Judge A and Judge B reasoning side-by-side
  - "Settle Tie-Break" button per Conflict row — opens a small inline form with PASS / FAIL choice that calls `POST /api/v1/settle-conflict`

- **Modify:** `backend/templates/marketplace.html`
  - Add `badge-conflict` CSS class support (colour defined in `dashboard.css`)

- **Modify:** `backend/static/css/dashboard.css`
  - Add `--color-escrow-conflict` CSS custom property (amber-purple gradient or solid purple)
  - Add `.badge-conflict` class

## Files to change

| File | Change |
|---|---|
| `backend/database/db.py` | Add 5 migrations; add `conflict_rfp()`, `settle_conflict()`, `get_conflict_rfps()` functions; update `get_active_pacts()` to include new columns and Conflict status |
| `backend/app.py` | Add `POST /api/v1/report-conflict` and `POST /api/v1/settle-conflict` routes; update `GET /` to pass conflict pacts to template |
| `backend/agents/assessor.py` | Refactor `reason` node into parallel fan-out: `reason_a` (Groq) + `reason_b` (Gemini); add `consensus` node; add `report_conflict` node; update `AssessorState` with new fields |
| `backend/templates/dashboard.html` | Conflict badge, side-by-side reasoning panel, Settle button |
| `backend/templates/marketplace.html` | Conflict badge |
| `backend/static/css/dashboard.css` | `--color-escrow-conflict` + `.badge-conflict` |
| `requirements.txt` | Add `google-generativeai` |

## Files to create

None — all changes are to existing files.

## New dependencies

```
google-generativeai
```

Requires `GEMINI_API_KEY` environment variable. Free tier available at Google AI Studio.

## Rules for implementation

- No SQLAlchemy or ORMs — raw `sqlite3` with `?` parameterised queries only
- All templates extend `base.html`
- Use CSS variables — never hardcode hex values in templates or CSS
- `reason_a` and `reason_b` must run **concurrently** using `asyncio.gather()` inside the LangGraph node, not sequentially
- Judge A must use Groq (`llama-3.3-70b-versatile`); Judge B must use Google Gemini (`gemini-1.5-flash`)
- The `consensus` node must be pure logic — no LLM calls
- `POST /api/v1/report-conflict` must return 409 if RFP is not `Locked`
- `POST /api/v1/settle-conflict` must return 409 if RFP is not `Conflict`
- Conflict CSS colour must be defined as a CSS variable, not inline
- `get_active_pacts()` must include `Conflict` in its status filter

## Definition of done

- [ ] Two different LLM providers are called for every Locked RFP — visible in agent terminal logs
- [ ] When `FORCE_VERDICT_A=PASS` and `FORCE_VERDICT_B=FAIL` env vars are set, RFP transitions to `Conflict`
- [ ] Dashboard shows Conflict badge (purple/amber) for conflicted RFPs
- [ ] Dashboard shows Judge A and Judge B reasoning side-by-side on Conflict rows
- [ ] "Settle Tie-Break" PASS button transitions RFP to `Completed`
- [ ] "Settle Tie-Break" FAIL button transitions RFP to `Disputed`
- [ ] Unanimous PASS still auto-settles to `Completed` without human intervention
- [ ] Unanimous FAIL still auto-settles to `Disputed` without human intervention
- [ ] `rfps` table has all 5 new columns after server restart on existing DB
- [ ] `requirements.txt` includes `google-generativeai`
