# Plan: Human Command Center and Policy Mandate (Step 01)

## Context

The project has no code yet — only docs (PRD.md, CLAUDE.md, specs). This step bootstraps the entire backend/frontend skeleton and implements the human owner's control surface: wallet connection via Locus API key, spending mandate (budget caps), and a live dashboard showing wallet balance and pact activity.

---

## File Structure to Create

```
backend/
├── app.py                        # FastAPI app — all routes registered here
├── database/
│   └── db.py                     # SQLite init, parameterized query helpers
├── templates/
│   ├── base.html                 # Shell: Tailwind CDN, nav, block content
│   ├── dashboard.html            # Wallet status, balance, pacts feed
│   └── settings.html            # API key + mandate form
├── static/
│   ├── css/
│   │   └── dashboard.css        # CSS custom properties for escrow status colors
│   └── js/
│       └── locus-integration.js # Fetch wrappers: POST /mandate, GET /balance
└── requirements.txt
```

---

## Database Schema (SQLite — no ORM)

File: `backend/database/db.py`

```sql
CREATE TABLE IF NOT EXISTS owner (
    id               INTEGER PRIMARY KEY,
    locus_auth_token TEXT,
    max_task_budget  REAL    DEFAULT 0.0,
    daily_limit      REAL    DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS agent_policies (
    id                     INTEGER PRIMARY KEY,
    required_assessor_score REAL    DEFAULT 4.5,
    allowed_service_types  TEXT    DEFAULT '[]'   -- JSON-encoded list
);
```

Single-row tables (id=1). `db.py` exposes:
- `init_db()` — creates tables, inserts seed row if empty
- `get_owner()` → dict
- `update_mandate(token, max_budget, daily_limit)`
- `get_policy()` → dict
- `update_policy(required_assessor_score, allowed_service_types)`

All writes use parameterized `?` placeholders.

---

## Routes (`backend/app.py`)

| Method | Path                  | Auth   | Description |
|--------|-----------------------|--------|-------------|
| GET    | `/`                   | Public | Dashboard — reads `owner` from db, renders `dashboard.html` |
| GET    | `/settings`           | Public | Mandate form — reads current values, renders `settings.html` |
| POST   | `/api/v1/mandate`     | —      | JSON body: `{locus_auth_token, max_task_budget, daily_limit, required_assessor_score}`. Validates token against Locus `/api/pay/balance`; on success persists via `db.update_mandate` + `db.update_policy`; returns `{success, wallet_address, balance}` |
| GET    | `/api/v1/balance`     | —      | Reads stored token; calls Locus `GET /api/pay/balance`; returns `{balance, wallet_address}` |

`app.py` mounts `StaticFiles` at `/static` and `Jinja2Templates` at `backend/templates`.

---

## Locus API Integration (inside `app.py`)

Base URL: `https://beta-api.paywithlocus.com/api`

`POST /api/v1/mandate` validation:
```python
async with httpx.AsyncClient() as client:
    r = await client.get(
        "https://beta-api.paywithlocus.com/api/pay/balance",
        headers={"Authorization": f"Bearer {locus_auth_token}"},
        timeout=10,
    )
```
- `200` → token valid; persist + return balance
- non-200 → return 400 `{"error": "Invalid Locus API key"}`

`GET /api/v1/balance` uses the same pattern with the stored token.

---

## Templates

**`base.html`**: Tailwind CSS CDN, top nav with links to `/` (Dashboard) and `/settings` (Settings), `{% block content %}{% endblock %}`.

**`dashboard.html`**: Extends base. Shows:
- Wallet status chip ("Connected" / "Not configured") using `--color-escrow-locked` etc.
- USDC balance (populated on page load via `locus-integration.js` calling `/api/v1/balance`)
- Truncated `wallet_address`
- Empty-state pacts table (columns: Task, Seller, Amount, Status) — populated in later steps

**`settings.html`**: Extends base. Form inputs:
- Locus API Key (password input, never echoed back from db)
- Max Task Budget (USDC)
- Daily Limit (USDC)
- Min Assessor Score (0–5)
- Submit → `locus-integration.js` POSTs JSON to `/api/v1/mandate`, shows success/error toast

---

## Static Files

**`dashboard.css`**:
```css
:root {
  --color-escrow-open:      #3b82f6;
  --color-escrow-locked:    #f59e0b;
  --color-escrow-completed: #10b981;
  --color-escrow-disputed:  #ef4444;
}
```

**`locus-integration.js`**:
- `submitMandate(formData)` → `fetch("/api/v1/mandate", {method:"POST", body:JSON.stringify(...)})` → shows toast
- `refreshBalance()` → `fetch("/api/v1/balance")` → updates `#balance-display` element on dashboard

---

## Dependencies (`requirements.txt`)

```
fastapi
uvicorn[standard]
jinja2
httpx
werkzeug
python-multipart
```

---

## Verification (Definition of Done)

1. `pip install -r requirements.txt`
2. `uvicorn backend.app:app --reload` from repo root
3. Open `http://localhost:8000/settings` → enter a valid `claw_…` Locus API key + budget → submit
4. Page shows success toast; `/` dashboard now shows "Wallet Connected" + live USDC balance
5. `sqlite3 lescrow.db "SELECT locus_auth_token, max_task_budget, daily_limit FROM owner"` shows persisted values
6. Entering an invalid key returns an error toast without storing anything
