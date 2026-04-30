import asyncio
import os
import random
from pathlib import Path
from typing import TypedDict

import httpx
from groq import Groq
from langgraph.graph import END, StateGraph

SELLER_ID = "seller-agent-01"
SELLER_EMAIL = os.getenv("SELLER_EMAIL", "seller@lescrow.dev")
MARGIN = 0.85
SIMULATION_PATH = Path(os.getenv("SIMULATION_PATH", str(Path(__file__).parent.parent / "simulation_sandbox")))


class SellerState(TypedDict):
    base_url: str
    seller_id: str
    seller_email: str
    tier: str
    bid_probability: float
    min_bounty: float
    open_rfps: list
    profitable_rfps: list
    bids_placed: list


def _generate_fix(rfp: dict, seller_id: str = SELLER_ID) -> None:
    sandbox_file = rfp.get("sandbox_file")
    if not sandbox_file:
        return

    repo_file = SIMULATION_PATH / "repo" / sandbox_file
    if not repo_file.exists():
        print(f"[Seller:{seller_id}] sandbox file not found: {repo_file}")
        return

    broken_code = repo_file.read_text(encoding="utf-8")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print(f"[Seller:{seller_id}] GROQ_API_KEY not set — skipping fix generation")
        return

    client = Groq(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert Python developer. Return ONLY the fixed Python source code. No markdown fences, no explanation, no comments about the fix.",
                },
                {
                    "role": "user",
                    "content": f"Bug report: {rfp['task_spec']}\n\nBroken code:\n{broken_code}\n\nReturn only the complete fixed Python file.",
                },
            ],
            max_tokens=1024,
        )
        fixed_code = response.choices[0].message.content.strip()
        if fixed_code.startswith("```"):
            lines = fixed_code.splitlines()
            fixed_code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        pr_path = SIMULATION_PATH / "prs" / f"pr_{seller_id}_{rfp['id']}.py"
        pr_path.write_text(fixed_code, encoding="utf-8")
        print(f"[Seller:{seller_id}] Fix written to {pr_path.name}")
    except Exception as e:
        print(f"[Seller:{seller_id}] Fix generation failed for {sandbox_file}: {e}")


async def fetch_open_rfps(state: SellerState) -> SellerState:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{state['base_url']}/api/v1/rfps",
                params={"status": "Open"},
                timeout=10,
            )
            rfps = resp.json().get("rfps", []) if resp.status_code == 200 else []
        except httpx.RequestError:
            rfps = []
    return {**state, "open_rfps": rfps}


async def score_rfps(state: SellerState) -> SellerState:
    profitable = []
    for rfp in state["open_rfps"]:
        if rfp["max_budget"] < state["min_bounty"]:
            continue
        bid_amount = rfp["max_budget"] * MARGIN
        if bid_amount <= 0 or rfp["deadline_seconds"] <= 0:
            continue
        if random.random() >= state["bid_probability"]:
            continue
        profitable.append({**rfp, "_bid_amount": bid_amount})
    return {**state, "profitable_rfps": profitable}


async def submit_bids(state: SellerState) -> SellerState:
    placed = []
    seller_id = state["seller_id"]
    seller_email = state["seller_email"]
    async with httpx.AsyncClient() as client:
        for rfp in state["profitable_rfps"]:
            try:
                existing = await client.get(
                    f"{state['base_url']}/api/v1/rfps/{rfp['id']}/bids",
                    timeout=10,
                )
                bids = existing.json().get("bids", []) if existing.status_code == 200 else []
                if any(b["seller_id"] == seller_id for b in bids):
                    continue
            except httpx.RequestError:
                continue

            try:
                resp = await client.post(
                    f"{state['base_url']}/api/v1/bid",
                    json={
                        "rfp_id": rfp["id"],
                        "seller_id": seller_id,
                        "seller_email": seller_email,
                        "bid_amount": rfp["_bid_amount"],
                        "eta_seconds": min(rfp["deadline_seconds"], 1800),
                    },
                    timeout=20,
                )
                if resp.status_code == 200:
                    placed.append(rfp["id"])
                    print(f"[Seller:{seller_id}] Bid placed on RFP {rfp['id'][:8]}")
            except httpx.RequestError:
                continue

    return {**state, "bids_placed": placed}


async def check_assigned_locked(state: SellerState) -> SellerState:
    """Phase C — generate fix only for RFPs where this agent won the bid."""
    seller_id = state["seller_id"]
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{state['base_url']}/api/v1/rfps",
                params={"status": "Locked"},
                timeout=10,
            )
            locked = resp.json().get("rfps", []) if resp.status_code == 200 else []
        except httpx.RequestError:
            locked = []

    for rfp in locked:
        if rfp.get("assigned_seller_id") != seller_id:
            continue
        if not rfp.get("sandbox_file"):
            continue
        pr_path = SIMULATION_PATH / "prs" / f"pr_{seller_id}_{rfp['id']}.py"
        if not pr_path.exists():
            _generate_fix(rfp, seller_id)

    return state


def build_seller_graph() -> StateGraph:
    g = StateGraph(SellerState)
    g.add_node("fetch_open_rfps", fetch_open_rfps)
    g.add_node("score_rfps", score_rfps)
    g.add_node("submit_bids", submit_bids)
    g.add_node("check_assigned_locked", check_assigned_locked)
    g.set_entry_point("fetch_open_rfps")
    g.add_edge("fetch_open_rfps", "score_rfps")
    g.add_edge("score_rfps", "submit_bids")
    g.add_edge("submit_bids", "check_assigned_locked")
    g.add_edge("check_assigned_locked", END)
    return g.compile()


async def run_seller(
    base_url: str,
    seller_id: str = SELLER_ID,
    seller_email: str = SELLER_EMAIL,
    tier: str = "intern",
    bid_probability: float = 0.90,
    min_bounty: float = 0.0,
    poll_interval: int = 8,
) -> None:
    graph = build_seller_graph()
    while True:
        await graph.ainvoke({
            "base_url": base_url,
            "seller_id": seller_id,
            "seller_email": seller_email,
            "tier": tier,
            "bid_probability": bid_probability,
            "min_bounty": min_bounty,
            "open_rfps": [],
            "profitable_rfps": [],
            "bids_placed": [],
        })
        await asyncio.sleep(poll_interval)
