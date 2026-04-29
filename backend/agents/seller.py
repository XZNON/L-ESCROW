import asyncio
import os
from typing import TypedDict

import httpx
from langgraph.graph import END, StateGraph

SELLER_ID = "seller-agent-01"
SELLER_EMAIL = os.getenv("SELLER_EMAIL", "seller@lescrow.dev")
MARGIN = 0.85  # bid at 85% of max_budget (15% headroom)


class SellerState(TypedDict):
    base_url: str
    open_rfps: list
    profitable_rfps: list
    bids_placed: list


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
        bid_amount = rfp["max_budget"] * MARGIN
        if bid_amount > 0 and rfp["deadline_seconds"] > 0:
            profitable.append({**rfp, "_bid_amount": bid_amount})
    return {**state, "profitable_rfps": profitable}


async def submit_bids(state: SellerState) -> SellerState:
    placed = []
    async with httpx.AsyncClient() as client:
        for rfp in state["profitable_rfps"]:
            # Skip if we already have a bid on this RFP
            try:
                existing = await client.get(
                    f"{state['base_url']}/api/v1/rfps/{rfp['id']}/bids",
                    timeout=10,
                )
                bids = existing.json().get("bids", []) if existing.status_code == 200 else []
                if any(b["seller_id"] == SELLER_ID for b in bids):
                    continue
            except httpx.RequestError:
                continue

            try:
                resp = await client.post(
                    f"{state['base_url']}/api/v1/bid",
                    json={
                        "rfp_id": rfp["id"],
                        "seller_id": SELLER_ID,
                        "seller_email": SELLER_EMAIL,
                        "bid_amount": rfp["_bid_amount"],
                        "eta_seconds": min(rfp["deadline_seconds"], 1800),
                    },
                    timeout=20,
                )
                if resp.status_code == 200:
                    placed.append(rfp["id"])
            except httpx.RequestError:
                continue

    return {**state, "bids_placed": placed}


def build_seller_graph() -> StateGraph:
    g = StateGraph(SellerState)
    g.add_node("fetch_open_rfps", fetch_open_rfps)
    g.add_node("score_rfps", score_rfps)
    g.add_node("submit_bids", submit_bids)
    g.set_entry_point("fetch_open_rfps")
    g.add_edge("fetch_open_rfps", "score_rfps")
    g.add_edge("score_rfps", "submit_bids")
    g.add_edge("submit_bids", END)
    return g.compile()


async def run_seller(base_url: str, poll_interval: int = 8) -> None:
    graph = build_seller_graph()
    while True:
        await graph.ainvoke({
            "base_url": base_url,
            "open_rfps": [],
            "profitable_rfps": [],
            "bids_placed": [],
        })
        await asyncio.sleep(poll_interval)
