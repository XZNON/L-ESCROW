╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
Plan: Agent Squad (Step 03)

Context

L-ESCROW's core lifecycle (Open → Verifying → Locked → Completed/Disputed) is functional at the API layer but no autonomous agents drive it. This step wires up three
LangGraph agents — Buyer, Seller, Assessor — that run concurrently and exercise the full lifecycle without human API calls. It also adds the missing POST
/api/v1/verify endpoint and makes the dashboard pacts feed live.

Design decisions confirmed with user:

- LangGraph for all agents (state machine per pact, checkpointing, ReAct pattern for Assessor)
- PASS verdict: DB → Completed. No Locus call; Seller Agent claims funds independently via Locus SDK (out of scope here).
- FAIL verdict: DB → Disputed + Hub attempts Locus session cancel (DELETE or POST .../cancel). If unsupported, return approval_url from session data for human
  revocation.

---

Files to modify

┌──────────────────────────────────┬──────────────────────────────────────────────────────────────────┐
│ File │ Change │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
│ backend/database/db.py │ Add 3 new functions + migrations for 3 new rfps columns │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
│ backend/app.py │ Add POST /api/v1/verify route; update GET / to pass active_pacts │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
│ backend/templates/dashboard.html │ Replace static empty pacts table with live Jinja2 loop │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
│ requirements.txt │ Add langgraph, anthropic │
└──────────────────────────────────┴──────────────────────────────────────────────────────────────────┘

Files to create

┌────────────────────────────┬────────────────────────────────────────────┐
│ File │ Purpose │
├────────────────────────────┼────────────────────────────────────────────┤
│ backend/agents/**init**.py │ Package marker │
├────────────────────────────┼────────────────────────────────────────────┤
│ backend/agents/buyer.py │ Buyer Agent — LangGraph graph │
├────────────────────────────┼────────────────────────────────────────────┤
│ backend/agents/seller.py │ Seller Agent — LangGraph graph │
├────────────────────────────┼────────────────────────────────────────────┤
│ backend/agents/assessor.py │ Assessor Agent — LangGraph graph (ReAct) │
├────────────────────────────┼────────────────────────────────────────────┤
│ backend/agents/runner.py │ python -m backend.agents.runner entrypoint │
└────────────────────────────┴────────────────────────────────────────────┘

---

Step 1 — DB changes (backend/database/db.py)

Migrations (add to init_db() try/except block)

"ALTER TABLE rfps ADD COLUMN assessor_id TEXT",
"ALTER TABLE rfps ADD COLUMN assessor_verdict TEXT",
"ALTER TABLE rfps ADD COLUMN verified_at TIMESTAMP",

New functions

get_locked_rfps() -> list[dict]
SELECT \* FROM rfps WHERE status = 'Locked' ORDER BY created_at ASC

get_active_pacts() -> list[dict]

- JOIN rfps + winning bid (status='Accepted') for dashboard display
- Returns rfps where status IN ('Locked', 'Completed', 'Disputed')
- Columns needed: task_spec, seller_id (from bids), bid_amount, rfp.status

complete_rfp(rfp_id, assessor_id, verdict)
UPDATE rfps SET status='Completed', assessor_id=?, assessor_verdict=?,
verified_at=CURRENT_TIMESTAMP WHERE id=?

dispute_rfp(rfp_id, assessor_id, verdict)
UPDATE rfps SET status='Disputed', assessor_id=?, assessor_verdict=?,
verified_at=CURRENT_TIMESTAMP WHERE id=?

---

Step 2 — POST /api/v1/verify (backend/app.py)

Pydantic model

class VerifyRequest(BaseModel):
rfp_id: str
assessor_id: str
verdict: str # "PASS" or "FAIL"
delivery_note: str # work description — used by Assessor LLM

Route logic

1.  rfp = db.get_rfp(rfp_id) → 404 if missing
2.  If rfp["status"] != "Locked" → return 409
3.  Validate verdict is "PASS" or "FAIL" → 400 if invalid
4.  PASS path:

- db.complete_rfp(rfp_id, assessor_id, "PASS")
- Return {"success": True, "status": "Completed"}

5.  FAIL path:

- db.dispute_rfp(rfp_id, assessor_id, "FAIL")
- Attempt Locus cancel: POST {LOCUS_API_BASE}/checkout/sessions/{escrow_session_id}/cancel with merchant token
- If cancel succeeds → return {"success": True, "status": "Disputed", "refund_initiated": True}
- If cancel fails (404/405/unsupported) → return {"success": True, "status": "Disputed", "refund_initiated": False, "note": "manual_resolution_required"}

Update GET / dashboard route

active_pacts = db.get_active_pacts()
return templates.TemplateResponse("dashboard.html", {
"request": request,
"wallet_connected": ...,
"owner": owner,
"policy": policy,
"active_pacts": active_pacts, # new
})

---

Step 3 — Dashboard template (backend/templates/dashboard.html)

Replace the static <tr> empty state in the pacts <tbody> with:
{% if active_pacts %}
{% for pact in active_pacts %}
{% set s = pact.status | lower %}
<tr class="border-t border-gray-800">
<td class="px-4 py-3 text-gray-200 truncate max-w-xs">{{ pact.task_spec }}</td>
<td class="px-4 py-3 text-gray-400 font-mono text-xs">{{ pact.seller_id[:12] if pact.seller_id else '—' }}…</td>
<td class="px-4 py-3 text-right text-white font-bold">
{{ "%.2f"|format(pact.bid_amount) if pact.bid_amount else '—' }}
<span class="text-gray-500 font-normal text-xs">USDC</span>
</td>
<td class="px-4 py-3 text-center">
<span class="px-2 py-0.5 rounded-full text-xs font-semibold text-white badge-{{ s }}">
{{ pact.status }}
</span>
</td>
</tr>
{% endfor %}
{% else %}

   <tr>
     <td colspan="4" class="px-4 py-10 text-center text-gray-600 text-sm">
       No active pacts — <a href="/marketplace" class="text-amber-400 hover:underline">open the Marketplace</a> to see agent activity.
     </td>
   </tr>
 {% endif %}

---

Step 4 — LangGraph Agents

Shared constants (backend/agents/runner.py or a shared module)

BASE_URL = "http://localhost:8000"

backend/agents/buyer.py

LangGraph State:
class BuyerState(TypedDict):
open_rfps: list
should_post: bool
rfp_id: str | None
owner: dict

Nodes:

1.  fetch_open_rfps — GET /api/v1/rfps?status=Open
2.  decide — if len(open_rfps) == 0 AND owner.max_task_budget > 0 → should_post=True
3.  post_rfp — POST /api/v1/rfp with task spec derived from mandate (simple hardcoded demo spec for MVP)

Edges: fetch_open_rfps → decide → conditional: post_rfp if should_post else END

Runner function: async def run_buyer(base_url, poll_interval=15) — loop calling graph.ainvoke() each cycle.

---

backend/agents/seller.py

LangGraph State:
class SellerState(TypedDict):
open_rfps: list
profitable_rfps: list
bids_placed: list

Nodes:

1.  fetch_open_rfps — GET /api/v1/rfps?status=Open
2.  score_rfps — filter: bid_amount = rfp.max_budget \* 0.85 (15% margin); ETA within deadline. Mark profitable if margin acceptable.
3.  submit_bids — POST /api/v1/bid for each profitable RFP not already bid on (check existing bids via GET /api/v1/rfps/{id}/bids)

Seller identity: hardcoded seller_id = "seller-agent-01", seller_email from owner email or config.

Edges: fetch_open_rfps → score_rfps → submit_bids → END

---

backend/agents/assessor.py (ReAct pattern)

LangGraph State:
class AssessorState(TypedDict):
locked_rfps: list
current_rfp: dict | None
delivery_note: str
llm_reasoning: str
verdict: str | None # "PASS" or "FAIL"
assessor_id: str

Nodes:

1.  fetch_locked_rfps — GET /api/v1/rfps?status=Locked
2.  pick_next — select first unprocessed locked RFP; if none → END
3.  reason (LLM call) — call Claude Haiku via anthropic SDK:

- System: "You are an impartial assessor. Given a task spec and a delivery note, output JSON: {verdict: 'PASS'|'FAIL', reasoning: string}"
- User: f"Task: {rfp.task_spec}\nDelivery: {delivery_note}"
- Parse JSON response → set verdict and llm_reasoning

4.  submit_verdict — POST /api/v1/verify with verdict + delivery_note + assessor_id

ReAct edges: fetch_locked_rfps → pick_next → reason → submit_verdict → loop back to pick_next

Delivery note for demo: Assessor polls locked RFPs and uses rfp.task_spec as both spec and delivery note (auto-PASS for MVP demo). Can be overridden via env var
FORCE_VERDICT=FAIL.

---

backend/agents/runner.py

import asyncio
from backend.agents.buyer import run_buyer
from backend.agents.seller import run_seller
from backend.agents.assessor import run_assessor

BASE_URL = "http://localhost:8000"

async def main():
await asyncio.gather(
run_buyer(BASE_URL, poll_interval=15),
run_seller(BASE_URL, poll_interval=8),
run_assessor(BASE_URL, poll_interval=5),
)

if **name** == "**main**":
asyncio.run(main())

---

Step 5 — requirements.txt

Add:
langgraph
anthropic

---

Verification (Definition of Done)

1.  POST /api/v1/verify PASS — curl with verdict: "PASS" on a Locked RFP → response status: Completed; GET /marketplace shows green Completed badge.
2.  POST /api/v1/verify FAIL — curl with verdict: "FAIL" on a Locked RFP → response status: Disputed; Locus cancel attempted; red Disputed badge in marketplace.
3.  409 guard — POST /api/v1/verify on an Open RFP → 409 response.
4.  Dashboard live — GET / shows real rows in Active Pacts table once any RFP is Locked/Completed.
5.  Runner end-to-end — python -m backend.agents.runner with server running: Buyer posts RFP → Seller bids (within 8s) → Assessor picks it up after Locked → verdict
    submitted → marketplace shows Completed.
6.  DB columns — after server restart on existing DB, rfps table has assessor_id, assessor_verdict, verified_at.
    ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
