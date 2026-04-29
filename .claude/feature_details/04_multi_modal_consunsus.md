## Feature Detail: Multi-Model Consensus (The Jury)

### Overview

To move L-ESCROW from "experimental" to "production-grade," we are implementing a Multi-Model Consensus mechanism for the Assessor Agent. Currently, a single LLM (Claude Haiku) makes the final decision on fund release. This introduces a "single point of failure" via model hallucination. The Consensus feature forces two independent LLMs from different providers to agree on a verdict before any money moves.

#### 1. The "Jury" Logic

The Assessor Agent will no longer be a linear script. It will now function as an orchestrator for a "Jury" of two models:

- Judge A: Claude 3.5 Haiku (via Anthropic)

- Judge B: Gemini 1.5 Flash or GPT-4o-mini (via Google/OpenAI)

##### The Rules of Settlement:

1. Unanimous PASS: If both Judges return PASS, the Hub calls complete_rfp.

2. Unanimous FAIL: If both Judges return FAIL, the Hub calls dispute_rfp and triggers a Locus refund.

3. The Conflict: If Judges disagree (e.g., Haiku says PASS, Gemini says FAIL), the RFP is moved to a new status: Conflict. No funds are moved automatically.

#### 2. Technical Requirements

##### LangGraph Refactor (backend/agents/assessor.py)

- **Parallel Execution**: Replace the single reason node with a fan-out pattern.

- **State Update**: New state fields: verdict_a, verdict_b, reasoning_a, reasoning_b.

- **Consensus Node**: A new logic node that compares the two verdicts.

- If verdict_a == verdict_b: Proceed to submit_verdict.

- If verdict_a != verdict_b: Proceed to report_conflict.

##### Backend API Updates (backend/app.py)

- New Status: Add Conflict to the valid status lifecycle.

- Conflict Endpoint: POST /api/v1/report-conflict — specifically for the Assessor to signal a stalemate.

- Verify Endpoint: Update POST /api/v1/verify to optionally store reasoning from both models for the audit trail.

##### Database Migrations (backend/database/db.py)

- New Columns:
  - judge_b_id (TEXT)

  - judge_b_verdict (TEXT)

  - conflict_notes (TEXT) - to store the differing reasonings.

#### 3. Human-in-the-Loop (HITL) UI

The Dashboard must now handle the "Stalemate" scenario:

- Conflict Badge: A high-visibility badge (Amber/Purple gradient) for Conflict status.

- Tie-Breaker View: A UI element that shows the reasoning from both Judge A and Judge B side-by-side.

- Manual Override: A "Settle Tie-Break" button for the human owner to manually push the status to Completed or Disputed.

4. Definition of Done

   [ ] Assessor Agent successfully calls two different LLM providers for every Locked pact.

   [ ] A disagreement between models correctly transitions the RFP to Conflict status.

   [ ] The Dashboard renders the Conflict state and displays reasonings from both models.

   [ ] Unanimous decisions still result in automated settlement (Completed/Disputed).

   [ ] requirements.txt updated with the second LLM provider's SDK.

#### 5. Security & Trust Narrative

This feature allows L-ESCROW to claim:

    "Funds are governed by a decentralized jury of independent AI models. No single model hallucination can trigger a payout."
