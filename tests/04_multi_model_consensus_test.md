# L-ESCROW — Full Application Test Guide
**Covers:** Steps 01–04 (Core Hub, Marketplace UI, Agent Squad, Multi-Model Consensus + Demo Mode)

This guide walks through every feature of L-ESCROW in order. Complete each section before moving to the next — later sections depend on state set up in earlier ones.

---

## Prerequisites

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. What you need
- A **Groq API key** — get one free at https://console.groq.com
- Two **Locus API keys** (buyer + merchant) — get them at https://paywithlocus.com
  - If you don't have real Locus keys, use **Demo Mode** (Section 6) — you only need the keys to be valid format for settings, but the full flow still works without real USDC

### 3. Two terminal windows
You'll need one terminal for the server and one for the agents. Open both before starting.

---

## Section 1 — Server Startup & Basic Health

### Start the server
**Terminal 1:**
```bash
uvicorn backend.app:app --reload
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process ...
INFO:     Started server process ...
INFO:     Application startup complete.
```

### Check the server is alive
```bash
curl http://localhost:8000/api/v1/rfps
```

Expected response:
```json
{"success": true, "rfps": []}
```

### Open the app in a browser
Navigate to: **http://localhost:8000**

**What to check:**
- [ ] Dashboard loads without errors
- [ ] Nav bar shows: Dashboard | Marketplace | Settings
- [ ] "Wallet" card shows "Not configured" with a "Connect wallet →" link
- [ ] "Balance" card shows `—`
- [ ] "Max Task Budget" card shows `—`
- [ ] Active Pacts table shows the empty state message

---

## Section 2 — Settings & Mandate (Step 01)

### Open Settings
Navigate to: **http://localhost:8000/settings**

**What to check:**
- [ ] Form renders with fields: Buyer API Key, Merchant API Key, Max Task Budget, Daily Limit, Min Assessor Score
- [ ] Fields are empty (fresh install) or pre-filled from DB

### Save a mandate via the UI
1. Enter your **Buyer Locus API key** in the "Buyer API Key" field
2. Enter your **Merchant Locus API key** in the "Merchant API Key" field
3. Enter `5` for Max Task Budget
4. Enter `20` for Daily Limit
5. Leave Min Assessor Score at `4.5`
6. Click **Save Settings**

**Expected:** Green toast notification — "Settings saved"

**What to check:**
- [ ] Toast appears bottom-right
- [ ] No error toast

### Verify mandate via API
```bash
curl http://localhost:8000/api/v1/balance
```

Expected response:
```json
{"success": true, "balance": <number or null>, "wallet_address": "<your wallet address>"}
```

> **Note:** `balance` may be `null` if your Locus account has no USDC — that's fine for Demo Mode testing. The key validation is that the request doesn't return an error.

### Check dashboard after mandate
Navigate to: **http://localhost:8000**

**What to check:**
- [ ] "Wallet" card now shows green dot + "Connected"
- [ ] "Wallet Address" line shows your wallet address (may take a moment to load)
- [ ] "Balance" card shows a number (or `0` — not `NaN` or `—`)
- [ ] "Max Task Budget" shows `5.00 USDC`

### Test invalid API key rejection
```bash
curl -X POST http://localhost:8000/api/v1/mandate \
  -H "Content-Type: application/json" \
  -d '{"locus_auth_token":"bad_key","merchant_locus_token":"also_bad","max_task_budget":5,"daily_limit":20,"required_assessor_score":4.5}'
```

Expected response:
```json
{"success": false, "error": "Invalid buyer Locus API key"}
```

**What to check:**
- [ ] Returns 400 status, not 500
- [ ] Error message is clear

---

## Section 3 — Marketplace UI (Step 02)

### Open Marketplace
Navigate to: **http://localhost:8000/marketplace**

**What to check:**
- [ ] Page loads with "Marketplace" heading
- [ ] Empty state shows (no RFPs yet)
- [ ] Page auto-refreshes every 10 seconds (check browser console — no JS errors)

### Create an RFP manually via API
```bash
curl -X POST http://localhost:8000/api/v1/rfp \
  -H "Content-Type: application/json" \
  -d '{"buyer_id":"test-buyer","task_spec":"Build a REST API for user authentication","max_budget":5.0,"deadline_seconds":1800,"min_reputation":0.0,"verification_type":"llm"}'
```

Expected response:
```json
{"success": true, "rfp_id": "<uuid>"}
```

Save the `rfp_id` — you'll need it below.

### Check RFP appears in Marketplace
Navigate to: **http://localhost:8000/marketplace** (or wait for auto-refresh)

**What to check:**
- [ ] RFP card appears with task spec text
- [ ] Status badge shows blue "Open"
- [ ] Max budget shows `5.00 USDC`
- [ ] "No bids yet" or empty bids section

### List RFPs via API
```bash
curl "http://localhost:8000/api/v1/rfps"
```
```bash
curl "http://localhost:8000/api/v1/rfps?status=Open"
```

**What to check:**
- [ ] First call returns all RFPs
- [ ] Second call returns only Open RFPs
- [ ] The RFP you created appears in both

### Submit a bid via API
Replace `<rfp_id>` with the ID from the create step:
```bash
curl -X POST http://localhost:8000/api/v1/bid \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<rfp_id>","seller_id":"seller-agent-01","seller_email":"seller@lescrow.dev","bid_amount":4.25,"eta_seconds":1800}'
```

Expected response (if Locus tokens are configured and bid is within budget):
```json
{
  "success": true,
  "bid_id": "<uuid>",
  "accepted": true,
  "status": "verifying",
  "checkout_url": "https://checkout.paywithlocus.com/...",
  "session_id": "..."
}
```

> If tokens aren't configured the `accepted` will be `false` with `reason: "locus_tokens_not_configured"` — that's expected.

### Check bid appears in Marketplace
Navigate to: **http://localhost:8000/marketplace**

**What to check:**
- [ ] Bid row appears under the RFP card with amount `4.25 USDC`
- [ ] Seller ID shows `seller-agent-01`

### List bids via API
```bash
curl "http://localhost:8000/api/v1/rfps/<rfp_id>/bids"
```

**What to check:**
- [ ] Returns the bid you submitted
- [ ] Bid has status `Pending` (if payment not triggered) or `Accepted`

---

## Section 4 — Full Locus Checkout Flow (Step 01 + 02 combined)

> Skip this section if you're using Demo Mode (Section 6) or don't have funded Locus accounts.

This tests the real Locus payment flow end-to-end.

### Create a fresh RFP
```bash
curl -X POST http://localhost:8000/api/v1/rfp \
  -H "Content-Type: application/json" \
  -d '{"buyer_id":"test-buyer","task_spec":"Write a Python script to parse CSV files","max_budget":5.0,"deadline_seconds":1800,"min_reputation":0.0,"verification_type":"llm"}'
```

Save the new `rfp_id`.

### Submit a qualifying bid
```bash
curl -X POST http://localhost:8000/api/v1/bid \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<rfp_id>","seller_id":"seller-agent-01","seller_email":"seller@lescrow.dev","bid_amount":4.00,"eta_seconds":1800}'
```

**Expected:** Response includes `"status": "verifying"` and a real `checkout_url`.

### Watch the status progression
```bash
curl "http://localhost:8000/api/v1/rfps?status=Verifying"
```

Wait up to 60 seconds, then:
```bash
curl "http://localhost:8000/api/v1/rfps?status=Locked"
```

**What to check:**
- [ ] RFP transitions from `Open` → `Verifying` → `Locked`
- [ ] Marketplace shows purple "Verifying" badge, then amber "Locked" badge
- [ ] "View Locus Checkout Session →" link appears on the marketplace card while Verifying/Locked

### Test over-budget bid rejection
```bash
curl -X POST http://localhost:8000/api/v1/bid \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<any_open_rfp_id>","seller_id":"test-seller","seller_email":"test@test.com","bid_amount":999.0,"eta_seconds":1800}'
```

Expected:
```json
{"success": true, "bid_id": "...", "accepted": false, "reason": "exceeds_budget"}
```

**What to check:**
- [ ] Bid is stored but not accepted
- [ ] No Locus checkout session is created
- [ ] RFP stays Open

---

## Section 5 — Agent Squad (Step 03)

### Prerequisites
- Server must be running (Terminal 1)
- `GROQ_API_KEY` must be set

### Start the agents
**Terminal 2:**

**On Windows CMD:**
```cmd
set GROQ_API_KEY=gsk_your_key_here
python -m backend.agents.runner
```

**On Windows PowerShell:**
```powershell
$env:GROQ_API_KEY="gsk_your_key_here"
python -m backend.agents.runner
```

**On Mac/Linux:**
```bash
GROQ_API_KEY=gsk_your_key_here python -m backend.agents.runner
```

Expected output:
```
[runner] Starting Agent Squad → http://localhost:8000
[runner]   Buyer   polls every 15s
[runner]   Seller  polls every  8s
[runner]   Assessor polls every  5s
[runner] Press Ctrl+C to stop.

[buyer] No open RFPs — posting new RFP...
[seller] Found 1 open RFP(s) — scoring...
[seller] Bidding on RFP <id>: 4.25 USDC
```

### Watch the full automated cycle

**Terminal 1 (server logs)** should show incoming HTTP requests from the agents.

**Browser:** Navigate to http://localhost:8000/marketplace — watch RFPs appear and move through statuses automatically.

**What to check within ~60 seconds:**
- [ ] Buyer Agent posts a new RFP (visible in marketplace as Open)
- [ ] Seller Agent submits a bid at 85% of max_budget
- [ ] Locus Checkout triggers (RFP goes Verifying)
- [ ] RFP transitions to Locked
- [ ] Assessor Agent picks it up — terminal shows "Calling Judge A (Llama 3.3) and Judge B (Gemma 2) concurrently"
- [ ] Terminal shows both verdicts: `Judge A (Llama 3.3): PASS | Judge B (Gemma 2): PASS`
- [ ] RFP transitions to Completed (green badge on dashboard)
- [ ] Dashboard "Active Pacts" table shows the completed pact

### Verify Buyer Agent deduplication
With an Open RFP already present, check the buyer doesn't post another one:
```
[buyer] 1 open RFP(s) found — skipping post
```

**What to check:**
- [ ] Buyer only posts when there are no Open RFPs
- [ ] Seller skips RFPs it has already bid on (`[seller] Already bid on <id> — skipping`)

### Verify Assessor polling
While a Locked RFP exists, Assessor should log every ~5 seconds:
```
[assessor] Calling Judge A (Llama 3.3) and Judge B (Gemma 2) concurrently for RFP <id>...
[assessor] Judge A (Llama 3.3): PASS | Judge B (Gemma 2): PASS
[assessor] Unanimous: PASS — auto-settling.
```

**What to check:**
- [ ] Assessor processes the Locked RFP
- [ ] Both judge verdicts are logged
- [ ] RFP moves to Completed or Disputed automatically

---

## Section 6 — Demo Mode (Step 04)

Demo Mode lets you test the full lifecycle without real USDC. Locus checkout sessions are real (you can see them on the Locus dashboard), but the payment step is simulated.

### Start server in Demo Mode

Stop the server (Ctrl+C in Terminal 1), then restart:

**Windows CMD:**
```cmd
set DEMO_MODE=true
uvicorn backend.app:app --reload
```

**Windows PowerShell:**
```powershell
$env:DEMO_MODE="true"
uvicorn backend.app:app --reload
```

**Mac/Linux:**
```bash
DEMO_MODE=true uvicorn backend.app:app --reload
```

### Check Demo Mode indicator
Navigate to: **http://localhost:8000**

**What to check:**
- [ ] Amber "Demo Mode" badge appears next to the "Command Center" heading
- [ ] Yellow note: "Locus checkout sessions are real — payment confirmation is simulated"
- [ ] "Run Demo Cycle" amber button appears in the top-right
- [ ] Marketplace also shows "Demo Mode" badge

### Run a Demo Cycle via the button
1. Go to **http://localhost:8000**
2. Click **"Run Demo Cycle"**

**What to check:**
- [ ] Button disables and shows "Starting…"
- [ ] Toast appears: "Demo cycle started — watch the Marketplace!"
- [ ] A new browser tab opens showing the real Locus checkout page
- [ ] Button shows "Cycle Running" then re-enables after ~12 seconds

### Watch the demo cycle progress
Navigate to: **http://localhost:8000/marketplace**

**Expected sequence (within 60 seconds):**
1. New RFP appears as "Open"
2. RFP moves to "Verifying" with a "View Locus Checkout Session →" link
3. After ~4 seconds (simulated payment): RFP moves to "Locked"
4. If agents are running: Assessor processes it → moves to "Completed" or "Conflict"

### Run Demo Cycle via API (alternative)
```bash
curl -X POST http://localhost:8000/api/v1/demo/run
```

Expected response:
```json
{
  "success": true,
  "rfp_id": "...",
  "bid_id": "...",
  "session_id": "...",
  "checkout_url": "https://checkout.paywithlocus.com/...",
  "message": "Demo cycle started — real Locus session created, payment simulates in 4s, Assessor will verify via LLM."
}
```

**What to check:**
- [ ] `checkout_url` is a real URL (not constructed manually from the session ID)
- [ ] Opening `checkout_url` in browser shows a real Locus checkout page

### Test Demo Mode guard
Stop server, restart **without** `DEMO_MODE=true`, then:
```bash
curl -X POST http://localhost:8000/api/v1/demo/run
```

Expected:
```json
{"success": false, "error": "Start server with DEMO_MODE=true"}
```

---

## Section 7 — Multi-Model Consensus (Step 04)

### Test 7A — Unanimous PASS (normal flow)

Start agents with no force flags:

**Windows CMD:**
```cmd
set GROQ_API_KEY=gsk_your_key_here
python -m backend.agents.runner
```

**Mac/Linux:**
```bash
GROQ_API_KEY=gsk_your_key_here python -m backend.agents.runner
```

Run a Demo Cycle (Section 6), then watch agent terminal.

**Expected agent output:**
```
[assessor] Calling Judge A (Llama 3.3) and Judge B (Gemma 2) concurrently for RFP <id>…
[assessor] Judge A (Llama 3.3): PASS | Judge B (Gemma 2): PASS
[assessor] Unanimous: PASS — auto-settling.
```

**What to check:**
- [ ] Both judges called concurrently (they appear in the same log line)
- [ ] Dashboard pact moves to green "Completed"
- [ ] No human intervention required

### Test 7B — Unanimous FAIL → auto Disputed

Stop agents (Ctrl+C in Terminal 2), restart with both verdicts forced to FAIL:

**Windows CMD:**
```cmd
set GROQ_API_KEY=gsk_your_key_here
set FORCE_VERDICT_A=FAIL
set FORCE_VERDICT_B=FAIL
python -m backend.agents.runner
```

**Windows PowerShell:**
```powershell
$env:GROQ_API_KEY="gsk_your_key_here"
$env:FORCE_VERDICT_A="FAIL"
$env:FORCE_VERDICT_B="FAIL"
python -m backend.agents.runner
```

**Mac/Linux:**
```bash
GROQ_API_KEY=gsk_your_key_here FORCE_VERDICT_A=FAIL FORCE_VERDICT_B=FAIL python -m backend.agents.runner
```

Run a Demo Cycle, then watch terminal.

**Expected agent output:**
```
[assessor] FORCED — Judge A: FAIL | Judge B: FAIL
[assessor] Unanimous: FAIL — auto-settling.
```

**What to check:**
- [ ] Dashboard pact moves to red "Disputed"
- [ ] No conflict panel shown (unanimous verdict, no HITL needed)

### Test 7C — Split Verdict → Conflict → Human tie-breaker

Stop agents, restart with split verdicts:

**Windows CMD:**
```cmd
set GROQ_API_KEY=gsk_your_key_here
set FORCE_VERDICT_A=PASS
set FORCE_VERDICT_B=FAIL
python -m backend.agents.runner
```

**Windows PowerShell:**
```powershell
$env:GROQ_API_KEY="gsk_your_key_here"
$env:FORCE_VERDICT_A="PASS"
$env:FORCE_VERDICT_B="FAIL"
python -m backend.agents.runner
```

**Mac/Linux:**
```bash
GROQ_API_KEY=gsk_your_key_here FORCE_VERDICT_A=PASS FORCE_VERDICT_B=FAIL python -m backend.agents.runner
```

Run a Demo Cycle, then watch terminal.

**Expected agent output:**
```
[assessor] FORCED — Judge A: PASS | Judge B: FAIL
[assessor] Conflict: Judge A=PASS, Judge B=FAIL — escalating to HITL.
```

**What to check on Dashboard (http://localhost:8000):**
- [ ] Pact row has a purple tint
- [ ] Status badge shows purple "Conflict"
- [ ] "Jury" column shows "View & Settle" button
- [ ] Clicking "View & Settle" expands a hidden row beneath

**Expanded conflict panel — check:**
- [ ] "Judge A — Llama 3.3" section with verdict PASS (green) and reasoning text
- [ ] "Judge B — Gemma 2" section with verdict FAIL (red) and reasoning text
- [ ] "The two judges disagree. As the human owner, you have the final say." message
- [ ] "Release Funds (PASS)" green button
- [ ] "Refund Buyer (FAIL)" red button

**Settle as PASS:**
1. Click "Release Funds (PASS)"

**Expected:**
- [ ] Toast: "Settled as Completed"
- [ ] Page reloads
- [ ] Pact status changes to green "Completed"
- [ ] Conflict panel gone

**Run another demo cycle and settle as FAIL:**
1. Click "Refund Buyer (FAIL)"

**Expected:**
- [ ] Toast: "Settled as Disputed"
- [ ] Pact status changes to red "Disputed"

### Test via API directly (without agents)

You can manually trigger the conflict flow without running agents:

**Step 1 — Create and lock an RFP** (use Demo Mode + demo/run endpoint):
```bash
curl -X POST http://localhost:8000/api/v1/demo/run
```
Wait ~5 seconds for it to reach Locked status, then note the `rfp_id`.

**Step 2 — Manually report a conflict:**
```bash
curl -X POST http://localhost:8000/api/v1/report-conflict \
  -H "Content-Type: application/json" \
  -d '{
    "rfp_id": "<rfp_id>",
    "assessor_id": "test-assessor",
    "verdict_a": "PASS",
    "reasoning_a": "The work meets all requirements.",
    "verdict_b": "FAIL",
    "reasoning_b": "The delivery is incomplete."
  }'
```

Expected:
```json
{"success": true, "status": "Conflict"}
```

**Step 3 — Verify RFP is now Conflict:**
```bash
curl "http://localhost:8000/api/v1/rfps/<rfp_id>/bids"
```
```bash
curl http://localhost:8000/api/v1/rfps | python -m json.tool
```

**Step 4 — Settle via API:**
```bash
curl -X POST http://localhost:8000/api/v1/settle-conflict \
  -H "Content-Type: application/json" \
  -d '{"rfp_id": "<rfp_id>", "verdict": "PASS"}'
```

Expected:
```json
{"success": true, "status": "Completed", "verdict": "PASS"}
```

**What to check:**
- [ ] 409 if you call `report-conflict` on a non-Locked RFP
- [ ] 409 if you call `settle-conflict` on a non-Conflict RFP
- [ ] 400 if verdict is not `PASS` or `FAIL`

---

## Section 8 — API Guard Rails

These test the error handling on all routes.

### RFP not found
```bash
curl http://localhost:8000/api/v1/rfps/nonexistent-id/bids
```
Expected: `{"success": false, "error": "RFP not found"}` with status 404

### Bid on non-Open RFP
Get a Locked or Completed RFP id, then:
```bash
curl -X POST http://localhost:8000/api/v1/bid \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<locked_rfp_id>","seller_id":"x","seller_email":"x@x.com","bid_amount":1.0,"eta_seconds":60}'
```
Expected: `{"success": false, "error": "RFP is already Locked"}` with status 409

### Verify non-Locked RFP
```bash
curl -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<open_rfp_id>","assessor_id":"x","verdict":"PASS","delivery_note":"done"}'
```
Expected: 409

### Invalid verdict
```bash
curl -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<any>","assessor_id":"x","verdict":"MAYBE","delivery_note":"done"}'
```
Expected: `{"success": false, "error": "verdict must be PASS or FAIL"}` with status 400

### Demo endpoint without Demo Mode
```bash
curl -X POST http://localhost:8000/api/v1/demo/run
```
(server not started with `DEMO_MODE=true`)

Expected: `{"success": false, "error": "Start server with DEMO_MODE=true"}` with status 400

---

## Section 9 — Full End-to-End Test (Demo Mode Recommended)

This is the complete happy-path test from zero to Completed in one run.

### Setup
1. Ensure `lescrow.db` exists and mandate is saved (Settings page)
2. Start server with Demo Mode: `DEMO_MODE=true uvicorn backend.app:app --reload`
3. Start agents: `GROQ_API_KEY=gsk_... python -m backend.agents.runner`

### Execute
1. Open **http://localhost:8000** in your browser
2. Click **"Run Demo Cycle"**
3. Watch the new tab — it shows a real Locus checkout session page
4. Switch back to Dashboard and watch the Active Pacts table update live
5. Open **http://localhost:8000/marketplace** in a second tab

### Expected full sequence
| Time | Event | Dashboard | Marketplace |
|------|-------|-----------|-------------|
| 0s | Demo cycle triggered | — | New RFP appears, Open (blue) |
| ~1s | Locus session created | — | Status: Verifying (purple) + checkout link |
| ~4s | Payment simulated | — | Status: Locked (amber) |
| ~5–15s | Assessor picks up RFP | — | — |
| ~15s | Both LLM judges return PASS | Pact appears | — |
| ~15s | Verdict submitted | Status: Completed (green) | Status: Completed (green) |

**Final state checks:**
- [ ] Active Pacts table shows the pact with green "Completed" badge
- [ ] Seller ID shows `seller-agent-01`
- [ ] Amount shows the bid amount in USDC
- [ ] Marketplace card shows green "Completed" badge

---

## Section 10 — Reset / Clean State

To start fresh between tests:

### Delete the database
```bash
# Windows
del lescrow.db

# Mac/Linux
rm lescrow.db
```

The database is recreated automatically on next server start.

### Check DB is clean
```bash
curl http://localhost:8000/api/v1/rfps
```
Expected: `{"success": true, "rfps": []}`

---

## Quick Reference — All curl Commands

```bash
# Health check
curl http://localhost:8000/api/v1/rfps

# Balance check
curl http://localhost:8000/api/v1/balance

# Create RFP
curl -X POST http://localhost:8000/api/v1/rfp \
  -H "Content-Type: application/json" \
  -d '{"buyer_id":"me","task_spec":"Do something","max_budget":5.0,"deadline_seconds":1800,"min_reputation":0.0,"verification_type":"llm"}'

# List all RFPs
curl http://localhost:8000/api/v1/rfps

# List by status
curl "http://localhost:8000/api/v1/rfps?status=Open"
curl "http://localhost:8000/api/v1/rfps?status=Locked"
curl "http://localhost:8000/api/v1/rfps?status=Conflict"

# Submit bid
curl -X POST http://localhost:8000/api/v1/bid \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<id>","seller_id":"seller-1","seller_email":"s@s.com","bid_amount":4.0,"eta_seconds":1800}'

# Manual verify (unanimous)
curl -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<id>","assessor_id":"me","verdict":"PASS","delivery_note":"done"}'

# Report conflict
curl -X POST http://localhost:8000/api/v1/report-conflict \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<id>","assessor_id":"me","verdict_a":"PASS","reasoning_a":"Looks good","verdict_b":"FAIL","reasoning_b":"Missing tests"}'

# Settle conflict
curl -X POST http://localhost:8000/api/v1/settle-conflict \
  -H "Content-Type: application/json" \
  -d '{"rfp_id":"<id>","verdict":"PASS"}'

# Run demo cycle (DEMO_MODE=true required)
curl -X POST http://localhost:8000/api/v1/demo/run

# Debug a transaction
curl http://localhost:8000/api/v1/debug/payment/<transaction_id>
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `NaN` balance on dashboard | Wrong Locus API field | Ensure you're using a real `claw_...` key; the field returned is `usdc_balance` |
| `{"error": "model_not_found"}` from Groq | Deprecated model | Assessor uses `llama-3.3-70b-versatile` + `gemma2-9b-it` — check your Groq key has access |
| Agents start but nothing happens | No Open RFPs, no mandate | Set `max_task_budget > 0` in Settings first |
| RFP stuck on Verifying (> 60s) | Payment polling timed out | Check Locus tokens are valid; or use Demo Mode |
| `409 RFP is Verifying` on bid | RFP already in checkout | Wait for it to resolve (Locked or revert to Open) |
| `DEMO_MODE` not recognized (Windows CMD) | PowerShell vs CMD syntax | Use `set DEMO_MODE=true` in CMD or `$env:DEMO_MODE="true"` in PowerShell |
| Conflict panel not showing on dashboard | RFP not in Conflict status | Use `FORCE_VERDICT_A=PASS FORCE_VERDICT_B=FAIL` to force a split |
| `module not found: backend.agents` | Wrong working directory | Run all commands from the repo root (`C:\Users\XZNON\Dione`) |
