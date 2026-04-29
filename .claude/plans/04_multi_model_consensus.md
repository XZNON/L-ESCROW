# Plan: Multi-Model Consensus (Step 04)

## Context

Step 03 (Agent Squad) introduced a single Groq LLM judge in the Assessor Agent. A single model hallucination can wrongly release or claw back escrow funds. This step replaces the single-judge pattern with a two-judge "Jury" (Llama 3.3 70B + Gemma 2 9B, both via Groq) that must agree before funds move. Disagreements transition the RFP to a new `Conflict` status and surface a Human-in-the-Loop tie-breaker UI on the dashboard so the owner can manually resolve stalemates.

**Prerequisite**: `feature/model-consensus` was branched from `main`, not `feature/agent-squad`. First action was `git merge feature/agent-squad --no-edit`.

---

## Files Changed

| File | Change |
|---|---|
| `backend/database/db.py` | 5 new migrations; `conflict_rfp()`, `settle_conflict()`; updated `get_active_pacts()` |
| `backend/app.py` | `POST /api/v1/report-conflict`, `POST /api/v1/settle-conflict`, `ConflictRequest`, `SettleRequest` models |
| `backend/agents/assessor.py` | Full refactor — dual-judge jury with `reason_judges`, `consensus`, `report_conflict` nodes |
| `backend/templates/dashboard.html` | Conflict badge, side-by-side reasoning panel, Settle buttons |
| `backend/static/css/dashboard.css` | `--color-escrow-conflict`, `.badge-conflict`, `.status-conflict` |
| `backend/agents/runner.py` | Updated docstring for env vars |
| `requirements.txt` | No new dependencies (both judges use existing `groq` SDK) |

---

## Step 1 — DB (`backend/database/db.py`)

### Migrations added
```python
"ALTER TABLE rfps ADD COLUMN judge_a_verdict TEXT",
"ALTER TABLE rfps ADD COLUMN judge_a_reasoning TEXT",
"ALTER TABLE rfps ADD COLUMN judge_b_verdict TEXT",
"ALTER TABLE rfps ADD COLUMN judge_b_reasoning TEXT",
"ALTER TABLE rfps ADD COLUMN conflict_notes TEXT",
```

### New functions
**`conflict_rfp(rfp_id, verdict_a, reasoning_a, verdict_b, reasoning_b)`**
- Sets `status = 'Conflict'`, stores both verdicts/reasonings and a `conflict_notes` summary

**`settle_conflict(rfp_id, assessor_id, verdict)`**
- Delegates to existing `complete_rfp()` (PASS) or `dispute_rfp()` (FAIL)

### Updated `get_active_pacts()`
- Added `'Conflict'` to status filter
- Added `judge_a_verdict`, `judge_a_reasoning`, `judge_b_verdict`, `judge_b_reasoning` to SELECT

---

## Step 2 — API Routes (`backend/app.py`)

### `POST /api/v1/report-conflict`
- Body: `ConflictRequest` (rfp_id, assessor_id, verdict_a, reasoning_a, verdict_b, reasoning_b)
- Guards: 400 if verdicts invalid, 404 if RFP missing, 409 if RFP not `Locked`
- Calls `db.conflict_rfp()` → returns `{"success": True, "status": "Conflict"}`

### `POST /api/v1/settle-conflict`
- Body: `SettleRequest` (rfp_id, verdict)
- Guards: 400 if verdict invalid, 404 if RFP missing, 409 if RFP not `Conflict`
- Calls `db.settle_conflict()`, attempts Locus cancel on FAIL (same pattern as `/api/v1/verify`)
- Returns `{"success": True, "status": "Completed"|"Disputed"}`

---

## Step 3 — Assessor Agent (`backend/agents/assessor.py`)

### New graph topology
```
fetch_locked_rfps → pick_next →(no rfp → END)
                              ↓
                         reason_judges   ← calls Llama 3.3 + Gemma 2 concurrently
                              ↓
                           consensus     ← pure logic, no LLM
                              ↓ (conditional)
              submit_verdict ←→ report_conflict
                              ↓
                           pick_next (loop)
```

### Judges
- **Judge A**: `llama-3.3-70b-versatile` via `_call_groq()`
- **Judge B**: `gemma2-9b-it` via `_call_gemma()` — different model family, same Groq API key

### Concurrent fan-out in `reason_judges`
```python
(va, ra), (vb, rb) = await asyncio.gather(
    _call_groq(rfp, delivery_note),
    _call_gemma(rfp, delivery_note),
)
```

### Env vars for testing
- `FORCE_VERDICT_A=PASS FORCE_VERDICT_B=FAIL` → forces Conflict
- `FORCE_VERDICT_A=FAIL FORCE_VERDICT_B=FAIL` → unanimous FAIL → auto Disputed

---

## Step 4 — CSS (`backend/static/css/dashboard.css`)

```css
--color-escrow-conflict: #a855f7;

.badge-conflict  { background-color: var(--color-escrow-conflict); }
.status-conflict { color: var(--color-escrow-conflict); }
```

---

## Step 5 — Dashboard Template (`backend/templates/dashboard.html`)

- Added 5th column "Jury" to Active Pacts table
- Conflict rows highlighted with purple tint
- "View & Settle" button toggles a hidden `<tr>` showing:
  - Judge A (Llama 3.3) verdict + reasoning
  - Judge B (Gemma 2) verdict + reasoning
  - "Release Funds (PASS)" and "Refund Buyer (FAIL)" buttons
- `settleConflict(rfpId, verdict)` JS calls `POST /api/v1/settle-conflict`

---

## Verification

1. `FORCE_VERDICT_A=PASS FORCE_VERDICT_B=FAIL` → run demo → RFP goes to **Conflict** → purple badge appears on dashboard
2. Click "View & Settle" → see both reasonings side-by-side
3. Click "Release Funds" → transitions to **Completed**
4. `FORCE_VERDICT_A=FAIL FORCE_VERDICT_B=FAIL` → unanimous FAIL → auto **Disputed**, no HITL needed
5. No force flags → both LLMs called, terminal logs show `Judge A (Llama 3.3): X | Judge B (Gemma 2): Y`
6. DB: `SELECT judge_a_verdict, judge_b_verdict FROM rfps LIMIT 5` returns populated rows
