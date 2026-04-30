"""
Run all L-ESCROW agents concurrently: 1 Buyer, 15 Sellers (3 tiers), 1 Assessor.

Usage:
    python -m backend.agents.runner

Environment variables:
    BASE_URL        FastAPI server URL (default: http://localhost:8000)
    GROQ_API_KEY    Required for Seller fix generation and both Assessor judges
"""

import asyncio
import os

from backend.agents.buyer import run_buyer
from backend.agents.assessor import run_assessor
from backend.agents.seller_population import make_seller_agents

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


async def main() -> None:
    agent_list = make_seller_agents(BASE_URL)
    print(f"[runner] Starting Agent Squad → {BASE_URL}")
    print(f"[runner]   Buyer    polls every 15s")
    print(f"[runner]   {len(agent_list)} Sellers across 3 tiers:")
    for _, label in agent_list:
        tier = label.split("-")[1]
        print(f"[runner]     {label}  ({tier})")
    print(f"[runner]   Assessor polls every  5s\n")

    await asyncio.gather(
        run_buyer(BASE_URL, poll_interval=15),
        *[coro for coro, _ in agent_list],
        run_assessor(BASE_URL, poll_interval=5),
    )


if __name__ == "__main__":
    asyncio.run(main())
