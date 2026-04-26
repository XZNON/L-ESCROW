from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend.database import db

LOCUS_API_BASE = "https://beta-api.paywithlocus.com/api"

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="L-ESCROW", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ── Page routes ──────────────────────────────────────────────────────────────

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


# ── API routes ────────────────────────────────────────────────────────────────

class MandateRequest(BaseModel):
    locus_auth_token: str
    max_task_budget: float
    daily_limit: float
    required_assessor_score: float = 4.5


@app.post("/api/v1/mandate")
async def save_mandate(body: MandateRequest):
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{LOCUS_API_BASE}/pay/balance",
                headers={"Authorization": f"Bearer {body.locus_auth_token}"},
                timeout=10,
            )
        except httpx.RequestError:
            return JSONResponse({"success": False, "error": "Could not reach Locus API"}, status_code=502)

    if resp.status_code != 200:
        return JSONResponse({"success": False, "error": "Invalid Locus API key"}, status_code=400)

    data = resp.json().get("data", {})
    db.update_mandate(body.locus_auth_token, body.max_task_budget, body.daily_limit)
    db.update_policy(body.required_assessor_score, [])

    return {
        "success": True,
        "wallet_address": data.get("wallet_address"),
        "balance": data.get("balance"),
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
