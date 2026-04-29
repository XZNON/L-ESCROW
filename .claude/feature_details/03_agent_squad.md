## Feature : The Agent Squad

### Overview

This feature implements the core autonomous logic using LangGraph. We will create three distinct agent personas that live in a backend/agents/ directory. These agents will use the Locus-enabled endpoints to fulfill the entire lifecycle of a pact without human intervention.

### The Personas

#### 1.The Buyer Agent (The Requester)

- Goal: Watch the "Mandate" and post RFPs when a task is needed.

- Logic: Reads owner policy → Calls POST /api/v1/rfp.

#### 2.The Seller Agent (The Worker)

- Goal: Maximize profit within constraints.

- Logic: Polls GET /api/v1/rfps → Filters for "Open" → Checks if max_budget is profitable(some criteria that decides if a agent bid is actually useful, depending of critacility of task, cost, and time.) → Calls POST /api/v1/bid.

#### The Assessor Agent (The Judge)

- Goal: Unbiased verification.

- Logic: Triggered when an RFP moves to Locked → Inspects "Task Spec" vs "Delivery" → Calls POST /api/v1/verify (PASS/FAIL).
