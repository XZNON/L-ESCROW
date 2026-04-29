"""
Run all three L-ESCROW agents concurrently.

Usage:
    python -m backend.agents.runner

Environment variables:
    BASE_URL        FastAPI server URL (default: http://localhost:8000)
    SELLER_EMAIL    Email for the Seller agent (default: seller@lescrow.dev)
    FORCE_VERDICT   Override Assessor verdict: "PASS" or "FAIL" (default: LLM decides)
    GROQ_API_KEY  Required for both Assessor judges (Judge A: llama-3.3-70b-versatile, Judge B: gemma2-9b-it)
"""

import asyncio
import os

from backend.agents.buyer import run_buyer
from backend.agents.seller import run_seller
from backend.agents.assessor import run_assessor

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


async def main() -> None:
    print(f"[runner] Starting Agent Squad → {BASE_URL}")
    print("[runner]   Buyer   polls every 15s")
    print("[runner]   Seller  polls every  8s")
    print("[runner]   Assessor polls every  5s")
    print("[runner] Press Ctrl+C to stop.\n")

    await asyncio.gather(
        run_buyer(BASE_URL, poll_interval=15),
        run_seller(BASE_URL, poll_interval=8),
        run_assessor(BASE_URL, poll_interval=5),
    )


if __name__ == "__main__":
    asyncio.run(main())
