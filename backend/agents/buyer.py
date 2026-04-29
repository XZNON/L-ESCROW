import asyncio
import uuid
from typing import TypedDict

import httpx
from langgraph.graph import END, StateGraph


class BuyerState(TypedDict):
    base_url: str
    open_rfps: list
    owner: dict
    should_post: bool
    rfp_id: str | None


async def fetch_open_rfps(state: BuyerState) -> BuyerState:
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


async def decide(state: BuyerState) -> BuyerState:
    owner = state["owner"]
    budget = owner.get("max_task_budget", 0)
    should_post = len(state["open_rfps"]) == 0 and budget > 0
    return {**state, "should_post": should_post}


async def post_rfp(state: BuyerState) -> BuyerState:
    owner = state["owner"]
    rfp_id = str(uuid.uuid4())
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{state['base_url']}/api/v1/rfp",
                json={
                    "buyer_id": "buyer-agent-01",
                    "task_spec": "Summarise the latest AI research papers from arxiv.org into a 500-word brief.",
                    "max_budget": owner.get("max_task_budget", 1.0),
                    "deadline_seconds": 3600,
                    "min_reputation": 0.0,
                    "verification_type": "llm",
                },
                timeout=10,
            )
        except httpx.RequestError:
            rfp_id = None
    return {**state, "rfp_id": rfp_id}


def _route_after_decide(state: BuyerState) -> str:
    return "post_rfp" if state["should_post"] else END


def build_buyer_graph() -> StateGraph:
    g = StateGraph(BuyerState)
    g.add_node("fetch_open_rfps", fetch_open_rfps)
    g.add_node("decide", decide)
    g.add_node("post_rfp", post_rfp)
    g.set_entry_point("fetch_open_rfps")
    g.add_edge("fetch_open_rfps", "decide")
    g.add_conditional_edges("decide", _route_after_decide)
    g.add_edge("post_rfp", END)
    return g.compile()


async def run_buyer(base_url: str, poll_interval: int = 15) -> None:
    graph = build_buyer_graph()
    while True:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{base_url}/api/v1/balance", timeout=10)
                owner_data = resp.json() if resp.status_code == 200 else {}
            except httpx.RequestError:
                owner_data = {}

        owner = {
            "max_task_budget": owner_data.get("balance", 0),
        }

        await graph.ainvoke({
            "base_url": base_url,
            "open_rfps": [],
            "owner": owner,
            "should_post": False,
            "rfp_id": None,
        })
        await asyncio.sleep(poll_interval)
