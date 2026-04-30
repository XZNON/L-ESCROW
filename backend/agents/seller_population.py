import random
from dataclasses import dataclass


@dataclass
class TierConfig:
    name: str
    count: int
    bid_probability: float
    min_bounty: float
    poll_min: int
    poll_max: int


TIERS = [
    TierConfig("intern", 5, 0.90, 0.0,  5,  8),
    TierConfig("pro",    5, 0.50, 20.0, 10, 15),
    TierConfig("expert", 5, 0.25, 45.0, 20, 30),
]


def make_seller_agents(base_url: str) -> list[tuple]:
    """Return list of (coroutine, label) for asyncio.gather()."""
    from backend.agents.seller import run_seller
    agents = []
    for tier in TIERS:
        for i in range(1, tier.count + 1):
            seller_id = f"seller-{tier.name}-{i:02d}"
            agents.append((
                run_seller(
                    base_url=base_url,
                    seller_id=seller_id,
                    seller_email=f"{seller_id}@lescrow.dev",
                    tier=tier.name,
                    bid_probability=tier.bid_probability,
                    min_bounty=tier.min_bounty,
                    poll_interval=random.randint(tier.poll_min, tier.poll_max),
                ),
                seller_id,
            ))
    return agents
