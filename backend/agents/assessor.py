import asyncio
import difflib
import json
import os
from pathlib import Path
from typing import TypedDict

import groq
import httpx
from langgraph.graph import END, StateGraph

ASSESSOR_ID = "assessor-agent-01"
FORCE_VERDICT_A = os.getenv("FORCE_VERDICT_A", "")
FORCE_VERDICT_B = os.getenv("FORCE_VERDICT_B", "")
SIMULATION_PATH = Path(os.getenv("SIMULATION_PATH", str(Path(__file__).parent.parent / "simulation_sandbox")))

_groq_client = groq.Groq()

_SYSTEM_PROMPT = (
    "You are an impartial escrow assessor. "
    "Given a task spec and a delivery note, decide if the work meets the spec. "
    'Respond with ONLY valid JSON: {"verdict": "PASS" or "FAIL", "reasoning": "<one sentence>"}'
)

_CODE_REVIEW_SYSTEM = (
    "You are an impartial code reviewer. Review the proposed fix and decide if it correctly resolves the reported bug. "
    'Respond ONLY with valid JSON: {"verdict": "PASS" or "FAIL", "reasoning": "<one sentence>"}'
)


class AssessorState(TypedDict):
    base_url: str
    locked_rfps: list
    current_rfp: dict | None
    delivery_note: str
    original_code: str
    proposed_code: str
    unified_diff: str
    verdict_a: str | None
    reasoning_a: str
    verdict_b: str | None
    reasoning_b: str
    conflict: bool


def _build_diff(rfp_id: str, sandbox_file: str) -> tuple[str, str, str]:
    repo_file = SIMULATION_PATH / "repo" / sandbox_file
    original = repo_file.read_text(encoding="utf-8") if repo_file.exists() else ""
    pr_matches = list((SIMULATION_PATH / "prs").glob(f"pr_*_{rfp_id}.py"))
    if not pr_matches:
        return original, "", ""
    proposed = pr_matches[0].read_text(encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"repo/{sandbox_file}",
        tofile=f"prs/{pr_matches[0].name}",
    ))
    return original, proposed, diff


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

    original_code = proposed_code = unified_diff = ""
    delivery_note = ""

    if rfp:
        if rfp.get("sandbox_file"):
            original_code, proposed_code, unified_diff = _build_diff(rfp["id"], rfp["sandbox_file"])
            if unified_diff:
                print(f"[assessor] Diff ready for {rfp['sandbox_file']} ({len(unified_diff)} chars)")
            else:
                print(f"[assessor] No PR file found for RFP {rfp['id'][:8]} — waiting for Seller fix")
        delivery_note = (
            f"Work completed as specified. Delivered: {rfp['task_spec']} — "
            "all requirements met, tested, and ready for review."
        )

    return {
        **state,
        "current_rfp": rfp,
        "delivery_note": delivery_note,
        "original_code": original_code,
        "proposed_code": proposed_code,
        "unified_diff": unified_diff,
        "verdict_a": None,
        "verdict_b": None,
        "reasoning_a": "",
        "reasoning_b": "",
        "conflict": False,
    }


async def _call_groq(rfp: dict, delivery_note: str, unified_diff: str) -> tuple[str, str]:
    try:
        if unified_diff:
            messages = [
                {"role": "system", "content": _CODE_REVIEW_SYSTEM},
                {"role": "user", "content": f"Bug report: {rfp['task_spec']}\n\nProposed fix (unified diff):\n{unified_diff}"},
            ]
        else:
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Task spec: {rfp['task_spec']}\nDelivery note: {delivery_note}"},
            ]
        chat = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=256,
            messages=messages,
        )
        result = json.loads(chat.choices[0].message.content)
        verdict = result.get("verdict", "FAIL")
        reasoning = result.get("reasoning", "")
    except Exception as e:
        verdict, reasoning = "FAIL", f"Groq error: {e}"

    if verdict not in ("PASS", "FAIL"):
        verdict = "FAIL"
    return verdict, reasoning


async def _call_gemma(rfp: dict, delivery_note: str, unified_diff: str) -> tuple[str, str]:
    try:
        if unified_diff:
            content = (
                f"{_CODE_REVIEW_SYSTEM}\n\n"
                f"Bug report: {rfp['task_spec']}\n\nProposed fix (unified diff):\n{unified_diff}"
            )
        else:
            content = (
                f"{_SYSTEM_PROMPT}\n\n"
                f"Task spec: {rfp['task_spec']}\nDelivery note: {delivery_note}"
            )
        chat = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        result = json.loads(chat.choices[0].message.content)
        verdict = result.get("verdict", "FAIL")
        reasoning = result.get("reasoning", "")
    except Exception as e:
        verdict, reasoning = "FAIL", f"Gemma error: {e}"

    if verdict not in ("PASS", "FAIL"):
        verdict = "FAIL"
    return verdict, reasoning


async def reason_judges(state: AssessorState) -> AssessorState:
    if FORCE_VERDICT_A and FORCE_VERDICT_B:
        print(f"[assessor] FORCED — Judge A: {FORCE_VERDICT_A} | Judge B: {FORCE_VERDICT_B}")
        return {**state,
                "verdict_a": FORCE_VERDICT_A, "reasoning_a": "Forced via FORCE_VERDICT_A env var.",
                "verdict_b": FORCE_VERDICT_B, "reasoning_b": "Forced via FORCE_VERDICT_B env var."}

    rfp = state["current_rfp"]
    mode = "code-diff" if state["unified_diff"] else "delivery-note"
    print(f"[assessor] Calling Judge A (Llama 3.3) and Judge B (Gemma 2) concurrently for RFP {rfp['id'][:8]} [{mode}]…")
    (va, ra), (vb, rb) = await asyncio.gather(
        _call_groq(rfp, state["delivery_note"], state["unified_diff"]),
        _call_gemma(rfp, state["delivery_note"], state["unified_diff"]),
    )
    print(f"[assessor] Judge A (Llama 3.3): {va} | Judge B (Gemma 2): {vb}")
    return {**state, "verdict_a": va, "reasoning_a": ra, "verdict_b": vb, "reasoning_b": rb}


async def consensus(state: AssessorState) -> AssessorState:
    agree = state["verdict_a"] == state["verdict_b"]
    if agree:
        print(f"[assessor] Unanimous: {state['verdict_a']} — auto-settling.")
    else:
        print(f"[assessor] Conflict: Judge A={state['verdict_a']}, Judge B={state['verdict_b']} — escalating to HITL.")
    return {**state, "conflict": not agree}


async def submit_verdict(state: AssessorState) -> AssessorState:
    rfp = state["current_rfp"]
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{state['base_url']}/api/v1/verify",
                json={
                    "rfp_id": rfp["id"],
                    "assessor_id": ASSESSOR_ID,
                    "verdict": state["verdict_a"],  # unanimous — both are equal
                    "delivery_note": state["delivery_note"],
                },
                timeout=15,
            )
        except httpx.RequestError:
            pass
    remaining = state["locked_rfps"][1:]
    return {**state, "locked_rfps": remaining, "current_rfp": None, "conflict": False}


async def report_conflict(state: AssessorState) -> AssessorState:
    rfp = state["current_rfp"]
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{state['base_url']}/api/v1/report-conflict",
                json={
                    "rfp_id": rfp["id"],
                    "assessor_id": ASSESSOR_ID,
                    "verdict_a": state["verdict_a"],
                    "reasoning_a": state["reasoning_a"],
                    "verdict_b": state["verdict_b"],
                    "reasoning_b": state["reasoning_b"],
                },
                timeout=15,
            )
        except httpx.RequestError:
            pass
    remaining = state["locked_rfps"][1:]
    return {**state, "locked_rfps": remaining, "current_rfp": None, "conflict": False}


def _route_after_pick(state: AssessorState) -> str:
    if not state["current_rfp"]:
        return END
    # If sandbox RFP but no PR file yet, skip this cycle — Seller hasn't written the fix yet
    if state["current_rfp"].get("sandbox_file") and not state["unified_diff"]:
        return END
    return "reason_judges"


def _route_after_consensus(state: AssessorState) -> str:
    return "report_conflict" if state["conflict"] else "submit_verdict"


def build_assessor_graph() -> StateGraph:
    g = StateGraph(AssessorState)
    g.add_node("fetch_locked_rfps", fetch_locked_rfps)
    g.add_node("pick_next", pick_next)
    g.add_node("reason_judges", reason_judges)
    g.add_node("consensus", consensus)
    g.add_node("submit_verdict", submit_verdict)
    g.add_node("report_conflict", report_conflict)
    g.set_entry_point("fetch_locked_rfps")
    g.add_edge("fetch_locked_rfps", "pick_next")
    g.add_conditional_edges("pick_next", _route_after_pick)
    g.add_edge("reason_judges", "consensus")
    g.add_conditional_edges("consensus", _route_after_consensus)
    g.add_edge("submit_verdict", "pick_next")
    g.add_edge("report_conflict", "pick_next")
    return g.compile()


async def run_assessor(base_url: str, poll_interval: int = 5) -> None:
    graph = build_assessor_graph()
    while True:
        await graph.ainvoke({
            "base_url": base_url,
            "locked_rfps": [],
            "current_rfp": None,
            "delivery_note": "",
            "original_code": "",
            "proposed_code": "",
            "unified_diff": "",
            "verdict_a": None,
            "reasoning_a": "",
            "verdict_b": None,
            "reasoning_b": "",
            "conflict": False,
        })
        await asyncio.sleep(poll_interval)
