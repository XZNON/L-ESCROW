import asyncio
import json
import os
from typing import TypedDict

import groq
import httpx
from langgraph.graph import END, StateGraph

ASSESSOR_ID = "assessor-agent-01"
FORCE_VERDICT = os.getenv("FORCE_VERDICT", "")  # set to "FAIL" to force failures


class AssessorState(TypedDict):
    base_url: str
    locked_rfps: list
    current_rfp: dict | None
    delivery_note: str
    llm_reasoning: str
    verdict: str | None


async def fetch_locked_rfps(state: AssessorState) -> AssessorState:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{state['base_url']}/api/v1/rfps",
                params={"status": "Locked"},
                timeout=10,
            )
            rfps = resp.json().get("rfps", []) if resp.status_code == 200 else []
        except httpx.RequestError:
            rfps = []
    return {**state, "locked_rfps": rfps}


async def pick_next(state: AssessorState) -> AssessorState:
    rfp = state["locked_rfps"][0] if state["locked_rfps"] else None
    # Simulate a delivery note confirming the work was completed (demo scenario)
    delivery_note = (
        f"Work completed as specified. Delivered: {rfp['task_spec']} — "
        "all requirements met, tested, and ready for review."
    ) if rfp else ""
    return {**state, "current_rfp": rfp, "delivery_note": delivery_note}


async def reason(state: AssessorState) -> AssessorState:
    if FORCE_VERDICT:
        return {**state, "verdict": FORCE_VERDICT, "llm_reasoning": "Forced via FORCE_VERDICT env var."}

    rfp = state["current_rfp"]
    client = groq.Groq()
    chat = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=256,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an impartial escrow assessor. "
                    "Given a task spec and a delivery note, decide if the work meets the spec. "
                    'Respond with ONLY valid JSON: {"verdict": "PASS" or "FAIL", "reasoning": "<one sentence>"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Task spec: {rfp['task_spec']}\n"
                    f"Delivery note: {state['delivery_note']}"
                ),
            },
        ],
    )
    try:
        result = json.loads(chat.choices[0].message.content)
        verdict = result.get("verdict", "FAIL")
        reasoning = result.get("reasoning", "")
    except (json.JSONDecodeError, IndexError, KeyError):
        verdict = "FAIL"
        reasoning = "Could not parse LLM response."

    if verdict not in ("PASS", "FAIL"):
        verdict = "FAIL"

    return {**state, "verdict": verdict, "llm_reasoning": reasoning}


async def submit_verdict(state: AssessorState) -> AssessorState:
    rfp = state["current_rfp"]
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{state['base_url']}/api/v1/verify",
                json={
                    "rfp_id": rfp["id"],
                    "assessor_id": ASSESSOR_ID,
                    "verdict": state["verdict"],
                    "delivery_note": state["delivery_note"],
                },
                timeout=15,
            )
        except httpx.RequestError:
            pass
    # Remove the processed RFP from the list and reset for next iteration
    remaining = state["locked_rfps"][1:]
    return {**state, "locked_rfps": remaining, "current_rfp": None, "verdict": None}


def _route_after_pick(state: AssessorState) -> str:
    return "reason" if state["current_rfp"] else END


def build_assessor_graph() -> StateGraph:
    g = StateGraph(AssessorState)
    g.add_node("fetch_locked_rfps", fetch_locked_rfps)
    g.add_node("pick_next", pick_next)
    g.add_node("reason", reason)
    g.add_node("submit_verdict", submit_verdict)
    g.set_entry_point("fetch_locked_rfps")
    g.add_edge("fetch_locked_rfps", "pick_next")
    g.add_conditional_edges("pick_next", _route_after_pick)
    g.add_edge("reason", "submit_verdict")
    g.add_edge("submit_verdict", "pick_next")  # loop back to process next locked RFP
    return g.compile()


async def run_assessor(base_url: str, poll_interval: int = 5) -> None:
    graph = build_assessor_graph()
    while True:
        await graph.ainvoke({
            "base_url": base_url,
            "locked_rfps": [],
            "current_rfp": None,
            "delivery_note": "",
            "llm_reasoning": "",
            "verdict": None,
        })
        await asyncio.sleep(poll_interval)
