import asyncio
from typing import TypedDict

import httpx
from langgraph.graph import END, StateGraph


class BuyerState(TypedDict):
    base_url: str
    sandbox_issues: list
    posted_count: int


async def fetch_sandbox_issues(state: BuyerState) -> BuyerState:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{state['base_url']}/api/v1/sandbox/issues",
                timeout=10,
            )
            issues = resp.json().get("issues", []) if resp.status_code == 200 else []
        except httpx.RequestError:
            issues = []
    # Only keep issues that are unresolved and have no active RFP
    pending = [i for i in issues if not i.get("resolved") and not i.get("active_rfp_id")]
    return {**state, "sandbox_issues": pending}


async def post_pending_rfps(state: BuyerState) -> BuyerState:
    posted = 0
    async with httpx.AsyncClient() as client:
        for issue in state["sandbox_issues"]:
            try:
                resp = await client.post(
                    f"{state['base_url']}/api/v1/rfp",
                    json={
                        "buyer_id": "buyer-agent-01",
                        "task_spec": issue["description"],
                        "max_budget": float(issue["bounty"]),
                        "deadline_seconds": 3600,
                        "min_reputation": 0.0,
                        "verification_type": "llm",
                        "issue_id": issue["id"],
                        "sandbox_file": issue["file"],
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"[Buyer] Posted RFP {data.get('rfp_id', '?')[:8]} for issue {issue['id']}: {issue['title']}")
                    posted += 1
            except httpx.RequestError:
                pass
    return {**state, "posted_count": posted}


def build_buyer_graph() -> StateGraph:
    g = StateGraph(BuyerState)
    g.add_node("fetch_sandbox_issues", fetch_sandbox_issues)
    g.add_node("post_pending_rfps", post_pending_rfps)
    g.set_entry_point("fetch_sandbox_issues")
    g.add_edge("fetch_sandbox_issues", "post_pending_rfps")
    g.add_edge("post_pending_rfps", END)
    return g.compile()


async def run_buyer(base_url: str, poll_interval: int = 15) -> None:
    graph = build_buyer_graph()
    while True:
        await graph.ainvoke({
            "base_url": base_url,
            "sandbox_issues": [],
            "posted_count": 0,
        })
        await asyncio.sleep(poll_interval)
