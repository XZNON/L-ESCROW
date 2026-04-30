# Spec: Simulation Sandbox

## Overview

Phase 5 builds a local "Mock-Git" environment that gives every agent a real artifact to work with. Instead of abstract task strings, the Buyer Agent posts RFPs sourced from a structured bug backlog (`issues.json`), the Seller Agent reads the broken source file, generates a real code fix via LLM, and writes it to a staging area. The Assessor Agent diffs the original against the proposed fix and feeds both to its dual-judge jury. A PASS verdict triggers `merge_fix()`, which copies the fix into the "production" repo — visibly resolving the bug in real-time. This makes the 15-agent demo concrete and compelling: broken code goes in, fixed code comes out, escrow settles automatically.

## Depends on

- Step 01 — Core Hub + Locus Checkout
- Step 02 — Marketplace UI
- Step 03 — Agent Squad (Buyer, Seller, Assessor)
- Step 04 — Multi-Model Consensus

## Routes

- `GET /sandbox` — Sandbox status page: shows all three repo files (broken/fixed state) with syntax-highlighted diffs — public
- `POST /api/v1/sandbox/reset` — Restores `repo/` to broken state from `_template/`; clears `prs/` — public
- `GET /api/v1/sandbox/issues` — Returns all issues from `issues.json` annotated with `resolved: bool` from DB — public (agent-facing)

## Database changes

Two new columns on `rfps` (added via `try/except ALTER TABLE` migrations in `init_db()`):

| Column | Type | Purpose |
|---|---|---|
| `issue_id` | TEXT | Links RFP to an entry in `issues.json` (e.g. `"bug-001"`) |
| `sandbox_file` | TEXT | Filename of the bug being fixed (e.g. `"math_utils.py"`) |

No new tables.

## Templates

- **Create:** `backend/templates/sandbox.html`
  - Extends `base.html`
  - Three file cards (one per seed scenario): filename, bounty, current status badge (Broken / Fixed)
  - Each card shows the raw file content from `repo/` in a `<pre>` block
  - If a PR exists in `prs/` for this file, show a unified text diff below the original
  - "Reset Sandbox" button calls `POST /api/v1/sandbox/reset` and reloads the page
  - Auto-refreshes every 10s (same `data-refresh` pattern as marketplace)

- **Modify:** `backend/templates/base.html`
  - Add "Sandbox" nav link alongside Dashboard / Marketplace / Settings

## Files to change

| File | Change |
|---|---|
| `backend/app.py` | Add `GET /sandbox`, `POST /api/v1/sandbox/reset`, `GET /api/v1/sandbox/issues`; import `SimulationManager`; call `sim_manager.merge_fix(rfp_id, sandbox_file)` inside `verify_rfp` on PASS verdict |
| `backend/database/db.py` | Add 2 `ALTER TABLE` migrations for `issue_id` + `sandbox_file`; update `create_rfp()` signature to accept both; add `get_completed_issue_ids() -> list[str]` helper |
| `backend/agents/buyer.py` | Replace hardcoded task spec with `GET /api/v1/sandbox/issues` call; post one RFP per unresolved issue (skip if Open RFP already exists for that `issue_id`); include `issue_id` and `sandbox_file` in `POST /api/v1/rfp` body |
| `backend/agents/seller.py` | On profitable RFPs with `sandbox_file` set: read `{SIMULATION_PATH}/repo/{sandbox_file}` → call Groq LLM to generate fix → write result to `{SIMULATION_PATH}/prs/pr_{seller_id}_{rfp_id}.py`; include file path in bid delivery note |
| `backend/agents/assessor.py` | For Locked RFPs with `sandbox_file` set: read `{SIMULATION_PATH}/repo/{sandbox_file}` as `original_code`; find and read `{SIMULATION_PATH}/prs/pr_*_{rfp_id}.py` as `proposed_code`; generate `unified_diff`; inject both into judge prompts; add `original_code`, `proposed_code`, `unified_diff` to `AssessorState` |
| `backend/templates/base.html` | Add Sandbox nav link |

## Files to create

| File | Purpose |
|---|---|
| `backend/simulation_sandbox/manager.py` | `SimulationManager` class: `reset_sandbox()`, `get_unresolved_issues()`, `merge_fix(rfp_id, sandbox_file)` |
| `backend/simulation_sandbox/issues.json` | Bug backlog — 3 entries (see Seed Scenarios below) |
| `backend/simulation_sandbox/_template/repo/math_utils.py` | Broken version: divide with no ZeroDivisionError guard |
| `backend/simulation_sandbox/_template/repo/auth.py` | Broken version: hardcoded `ADMIN_PASSWORD = "ADMIN_1234"` |
| `backend/simulation_sandbox/_template/repo/client.py` | Broken version: missing closing `)` on a dict literal |
| `backend/simulation_sandbox/repo/math_utils.py` | Live working copy (initially identical to `_template`) |
| `backend/simulation_sandbox/repo/auth.py` | Live working copy |
| `backend/simulation_sandbox/repo/client.py` | Live working copy |
| `backend/templates/sandbox.html` | Sandbox status page |

`backend/simulation_sandbox/prs/` directory must exist but start empty (add `.gitkeep`).

## New dependencies

No new pip packages. Uses `difflib` (stdlib) for unified diff generation.

## Seed scenarios

`issues.json` structure:

```json
[
  {
    "id": "bug-001",
    "title": "ZeroDivisionError in divide()",
    "file": "math_utils.py",
    "description": "The divide() function crashes when divisor is 0. Add a guard that raises ValueError with a descriptive message instead.",
    "bounty": 20
  },
  {
    "id": "bug-002",
    "title": "Hardcoded admin password in auth.py",
    "file": "auth.py",
    "description": "ADMIN_PASSWORD is hardcoded as 'ADMIN_1234'. Replace it with os.environ.get('ADMIN_PASSWORD') and raise EnvironmentError if the variable is not set.",
    "bounty": 50
  },
  {
    "id": "bug-003",
    "title": "Syntax error in client.py",
    "file": "client.py",
    "description": "A missing closing parenthesis on the CONFIG dict literal causes a SyntaxError. Fix the syntax so the module imports cleanly.",
    "bounty": 10
  }
]
```

## Rules for implementation

- No SQLAlchemy or ORMs — raw `sqlite3` with `?` parameterised queries only
- Parameterised queries only
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `SimulationManager` must use `pathlib.Path` exclusively — no `os.path` string manipulation
- `SIMULATION_PATH` env var overrides the default sandbox path; default = `Path(__file__).parent` (i.e. `backend/simulation_sandbox/`)
- `reset_sandbox()` must copy from `_template/repo/` to `repo/` and delete all files in `prs/` (except `.gitkeep`)
- `merge_fix(rfp_id, sandbox_file)` must find the PR file by glob `prs/pr_*_{rfp_id}.py`; if none found, log a warning and return without raising
- Seller LLM call must use Groq (`llama-3.3-70b-versatile`) with `GROQ_API_KEY` — same key already used by Assessor
- Seller must write only the fixed Python source to the PR file — no markdown, no explanation text
- Assessor judge prompts must include the unified diff when `sandbox_file` is set; fall back to `delivery_note` only when no sandbox file exists (backwards-compatible with non-sandbox RFPs)
- `create_rfp()` in `db.py` must keep existing positional signature intact; `issue_id` and `sandbox_file` should be keyword-only with `None` defaults
- `backend/simulation_sandbox/` except `_template/` and `issues.json` should be listed in `.gitignore`

## Definition of done

- [ ] `GET /sandbox` renders all three file cards with current content from `repo/`
- [ ] "Reset Sandbox" button restores broken state — re-visiting `/sandbox` shows the buggy code again
- [ ] `GET /api/v1/sandbox/issues` returns all 3 issues with `resolved: false` on a fresh DB
- [ ] Buyer Agent posts exactly one RFP per unresolved issue; skips issues that already have an Open/Locked/Completed RFP
- [ ] Seller Agent writes a `.py` file to `prs/` for each RFP it bids on — file is valid Python (no markdown)
- [ ] Assessor judge logs show the unified diff in the prompt when evaluating a sandbox RFP
- [ ] After unanimous PASS, `merge_fix()` copies the PR file to `repo/` — `/sandbox` shows the fixed code
- [ ] After `reset_sandbox()`, `repo/` files are back to broken state and `prs/` is empty
- [ ] `rfps` table has `issue_id` and `sandbox_file` columns after server restart on existing DB
- [ ] Non-sandbox RFPs (no `sandbox_file`) continue to work unchanged through the full lifecycle
