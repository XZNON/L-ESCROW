The goal of this phase is to create the visual and logical "crowding" of a real marketplace while engineering the costs to stay within pennies.

## Feature detail 05 — The Agent Population (15-Agent Economy)

### 1. Overview

This feature scales the Seller side of the marketplace from a single instance to a diverse population of 15 agents. These agents are categorized into three tiers (Intern, Pro, Expert), each with unique bidding behaviors, price sensitivities, and model assignments. To protect the developer's wallet, the system uses "Lazy Generation"—only the winning agent performs the high-cost code generation.

### 2. Agent Tier Definitions

The population is generated using a factory pattern in runner.py, distributing 15 agents across these profiles:
| Tier | Count | Bid Probability | Min Bounty | Speed (Poll) | Logic Profile |
|--------|-------|------------------|------------|--------------|-----------------------------------------------------------|
| Intern | 5 | 90% | $0 | 5–8s | Bids on everything; uses cheapest available model. |
| Pro | 5 | 50% | $20 | 10–15s | Selective; only bids on medium-to-high value tasks. |
| Expert | 5 | 25% | $45 | 20–30s | High-quality; only bids on premium bounties. |

### 3. Cost-Optimization Logic ("Lazy Fix")

To prevent 15 agents from calling the LLM simultaneously (which would incur 45+ expensive generation calls for 3 bugs), we implement a state-aware lifecycle:

1.  Phase A (The Bid): Agents analyze the RFP using pure Python logic (comparing `max_budget` and `task_spec` keywords). Cost: $0.00.

2.  Phase B (The Award): The Buyer Agent selects a winner based on price/reputation. The RFP status moves to `Locked`.

3.  Phase C (The Generation): ONLY the assigned Seller Agent detects the `Locked` status and triggers the `_generate_fix` LLM call. Cost: ~$0.01 per bug.
