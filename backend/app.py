import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import uuid

import httpx
from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend.database import db

LOCUS_API_BASE = "https://beta-api.paywithlocus.com/api"
CHECKOUT_BASE_URL = "https://checkout.beta.paywithlocus.com"

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="L-ESCROW", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ── Page routes ───────────────────────────────────────────────────────────────

@app.get("/")
async def dashboard(request: Request):
    owner = db.get_owner()
    policy = db.get_policy()
    wallet_connected = bool(owner.get("locus_auth_token"))
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "wallet_connected": wallet_connected, "owner": owner, "policy": policy},
    )


@app.get("/settings")
async def settings(request: Request):
    owner = db.get_owner()
    policy = db.get_policy()
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "owner": owner, "policy": policy},
    )


# ── Mandate API ───────────────────────────────────────────────────────────────

class MandateRequest(BaseModel):
    locus_auth_token: str
    merchant_locus_token: str
    max_task_budget: float
    daily_limit: float
    required_assessor_score: float = 4.5


@app.post("/api/v1/mandate")
async def save_mandate(body: MandateRequest):
    async with httpx.AsyncClient() as client:
        try:
            buyer_resp = await client.get(
                f"{LOCUS_API_BASE}/pay/balance",
                headers={"Authorization": f"Bearer {body.locus_auth_token}"},
                timeout=10,
            )
            merchant_resp = await client.get(
                f"{LOCUS_API_BASE}/pay/balance",
                headers={"Authorization": f"Bearer {body.merchant_locus_token}"},
                timeout=10,
            )
        except httpx.RequestError:
            return JSONResponse({"success": False, "error": "Could not reach Locus API"}, status_code=502)

    if buyer_resp.status_code != 200:
        return JSONResponse({"success": False, "error": "Invalid buyer Locus API key"}, status_code=400)
    if merchant_resp.status_code != 200:
        return JSONResponse({"success": False, "error": "Invalid merchant Locus API key"}, status_code=400)

    buyer_data = buyer_resp.json().get("data", {})
    db.update_mandate(body.locus_auth_token, body.merchant_locus_token, body.max_task_budget, body.daily_limit)
    db.update_policy(body.required_assessor_score, [])

    return {
        "success": True,
        "wallet_address": buyer_data.get("wallet_address"),
        "balance": buyer_data.get("balance"),
    }


@app.get("/api/v1/balance")
async def get_balance():
    owner = db.get_owner()
    token = owner.get("locus_auth_token")
    if not token:
        return JSONResponse({"success": False, "error": "No API key configured"}, status_code=400)

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{LOCUS_API_BASE}/pay/balance",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
        except httpx.RequestError:
            return JSONResponse({"success": False, "error": "Could not reach Locus API"}, status_code=502)

    if resp.status_code != 200:
        return JSONResponse({"success": False, "error": "Locus API error"}, status_code=resp.status_code)

    data = resp.json().get("data", {})
    return {"success": True, "balance": data.get("balance"), "wallet_address": data.get("wallet_address")}


# ── Marketplace page ──────────────────────────────────────────────────────────

@app.get("/marketplace")
async def marketplace(request: Request):
    rfps = db.get_rfps()
    rfps_with_bids = [{"rfp": r, "bids": db.get_bids_for_rfp(r["id"])} for r in rfps]
    return templates.TemplateResponse(
        "marketplace.html",
        {"request": request, "rfps_with_bids": rfps_with_bids},
    )


# ── Marketplace API ───────────────────────────────────────────────────────────

class RFPRequest(BaseModel):
    buyer_id: str
    task_spec: str
    max_budget: float
    deadline_seconds: int
    min_reputation: float = 0.0
    verification_type: str = "manual"


class BidRequest(BaseModel):
    rfp_id: str
    seller_id: str
    seller_email: str
    bid_amount: float
    eta_seconds: int


@app.post("/api/v1/rfp")
async def create_rfp(body: RFPRequest):
    rfp_id = str(uuid.uuid4())
    db.create_rfp(
        rfp_id, body.buyer_id, body.task_spec, body.max_budget,
        body.deadline_seconds, body.min_reputation, body.verification_type,
    )
    return {"success": True, "rfp_id": rfp_id}


async def _poll_and_confirm(
    transaction_id: str, bid_id: str, rfp_id: str,
    session_id: str, merchant_token: str,
) -> None:
    """Background task: poll session status until PAID, then lock the pact atomically."""
    for _ in range(30):  # max ~60 seconds (30 × 2s)
        await asyncio.sleep(2)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{LOCUS_API_BASE}/checkout/sessions/{session_id}",
                    headers={"Authorization": f"Bearer {merchant_token}"},
                    timeout=10,
                )
            if resp.status_code != 200:
                continue
            data = resp.json().get("data", resp.json())
            status = data.get("status", "")
            if status == "PAID":
                db.accept_bid(bid_id, rfp_id, session_id, transaction_id)
                return
            if status in ("EXPIRED", "CANCELLED"):
                db.revert_rfp_to_open(rfp_id)
                return
        except Exception:
            continue
    # Timed out — revert
    db.revert_rfp_to_open(rfp_id)


@app.post("/api/v1/bid")
async def create_bid(body: BidRequest, background_tasks: BackgroundTasks):
    rfp = db.get_rfp(body.rfp_id)
    if not rfp:
        return JSONResponse({"success": False, "error": "RFP not found"}, status_code=404)
    if rfp["status"] != "Open":
        return JSONResponse(
            {"success": False, "error": f"RFP is already {rfp['status']}"},
            status_code=409,
        )

    bid_id = str(uuid.uuid4())
    db.create_bid(bid_id, body.rfp_id, body.seller_id, body.seller_email, body.bid_amount, body.eta_seconds)

    if body.bid_amount > rfp["max_budget"]:
        return {"success": True, "bid_id": bid_id, "accepted": False, "reason": "exceeds_budget"}

    owner = db.get_owner()
    buyer_token = owner.get("locus_auth_token")
    merchant_token = owner.get("merchant_locus_token")
    if not buyer_token or not merchant_token:
        return {"success": True, "bid_id": bid_id, "accepted": False, "reason": "locus_tokens_not_configured"}

    # ── Step 1: Merchant creates a checkout session ───────────────────────────
    async with httpx.AsyncClient() as client:
        try:
            session_resp = await client.post(
                f"{LOCUS_API_BASE}/checkout/sessions",
                headers={"Authorization": f"Bearer {merchant_token}"},
                json={
                    "amount": str(body.bid_amount),
                    "description": f"L-ESCROW: {rfp['task_spec'][:80]}",
                    "metadata": {"rfp_id": body.rfp_id, "bid_id": bid_id},
                },
                timeout=15,
            )
        except httpx.RequestError:
            return {"success": True, "bid_id": bid_id, "accepted": False, "error": "locus_unreachable"}

    if session_resp.status_code not in (200, 201):
        err = session_resp.json().get("message") or session_resp.json().get("error") or "session_creation_failed"
        return {"success": True, "bid_id": bid_id, "accepted": False, "error": err, "locus_status": session_resp.status_code}

    session_data = session_resp.json().get("data", session_resp.json())
    session_id = session_data.get("id") or session_data.get("sessionId") or session_data.get("session_id")
    webhook_secret = session_data.get("webhookSecret") or session_data.get("webhook_secret") or ""
    checkout_url = (
        session_data.get("checkoutUrl")
        or session_data.get("checkout_url")
        or session_data.get("url")
        or f"{CHECKOUT_BASE_URL}/{session_id}"
    )

    # ── Step 2: Mark RFP as Verifying (before paying) ─────────────────────────
    db.set_rfp_verifying(body.rfp_id, session_id, webhook_secret, bid_id)

    # ── Step 3: Buyer agent pays the session ───────────────────────────────────
    async with httpx.AsyncClient() as client:
        try:
            pay_resp = await client.post(
                f"{LOCUS_API_BASE}/checkout/agent/pay/{session_id}",
                headers={"Authorization": f"Bearer {buyer_token}"},
                json={"payerEmail": body.seller_email},
                timeout=15,
            )
        except httpx.RequestError:
            db.revert_rfp_to_open(body.rfp_id)
            return {"success": True, "bid_id": bid_id, "accepted": False, "error": "locus_unreachable_on_pay"}

    if pay_resp.status_code not in (200, 201, 202):
        err = pay_resp.json().get("message") or pay_resp.json().get("error") or "payment_failed"
        db.revert_rfp_to_open(body.rfp_id)
        return {"success": True, "bid_id": bid_id, "accepted": False, "error": err, "locus_status": pay_resp.status_code}

    pay_data = pay_resp.json().get("data", {})
    transaction_id = pay_data.get("transaction_id") or pay_data.get("transactionId") or ""

    # ── Step 4: Poll for confirmation in the background ───────────────────────
    background_tasks.add_task(
        _poll_and_confirm, transaction_id, bid_id, body.rfp_id, session_id, merchant_token
    )

    return {
        "success": True,
        "bid_id": bid_id,
        "accepted": True,
        "status": "verifying",
        "checkout_url": checkout_url,
        "session_id": session_id,
        "transaction_id": transaction_id,
    }


@app.get("/api/v1/rfps")
async def list_rfps(status: Optional[str] = Query(default=None)):
    return {"success": True, "rfps": db.get_rfps(status=status)}


@app.get("/api/v1/rfps/{rfp_id}/bids")
async def list_bids(rfp_id: str):
    rfp = db.get_rfp(rfp_id)
    if not rfp:
        return JSONResponse({"success": False, "error": "RFP not found"}, status_code=404)
    return {"success": True, "bids": db.get_bids_for_rfp(rfp_id)}


# ── Debug ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/debug/payment/{transaction_id}")
async def debug_payment(transaction_id: str):
    owner = db.get_owner()
    merchant_token = owner.get("merchant_locus_token")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{LOCUS_API_BASE}/checkout/agent/payments/{transaction_id}",
            headers={"Authorization": f"Bearer {merchant_token}"},
            timeout=10,
        )
    return {"status_code": resp.status_code, "body": resp.json()}


# ── Locus Webhook ─────────────────────────────────────────────────────────────

@app.post("/api/v1/webhook/locus")
async def locus_webhook(request: Request):
    body_bytes = await request.body()
    signature_header = request.headers.get("X-Signature-256", "")
    event_name = request.headers.get("X-Webhook-Event", "")
    session_id = request.headers.get("X-Session-Id", "")

    # Look up the rfp to get the stored webhook secret
    rfp = db.get_rfp_by_session(session_id) if session_id else None

    if rfp and rfp.get("webhook_secret"):
        expected = "sha256=" + hmac.new(
            rfp["webhook_secret"].encode(),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()  # hmac.new is the stdlib alias
        if not hmac.compare_digest(signature_header, expected):
            return JSONResponse({"error": "invalid signature"}, status_code=401)

    if event_name == "checkout.session.paid" and rfp:
        bid_id = rfp.get("verifying_bid_id")
        if bid_id and rfp["status"] in ("Verifying", "Open"):
            payload = await request.json() if not body_bytes else __import__("json").loads(body_bytes)
            tx_hash = payload.get("data", {}).get("paymentTxHash", "")
            db.accept_bid(bid_id, rfp["id"], session_id, tx_hash)

    return {"received": True}
