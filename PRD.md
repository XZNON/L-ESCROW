# PRD: Project L-ESCROW (Autonomous Procurement & Escrow)

##### Version: 1.0 (Hackathon MVP)

##### Status: Implementation Ready

## 1. Overview

## Product Name

L-ESCROW

### Problem Statement

The "Agentic Economy" is currently paralyzed by a trust and settlement gap. AI agents can find tools, but they cannot safely negotiate price-for-performance or guarantee quality. Traditional payments (Stripe/PayPal) are too expensive for micro-tasks and too slow for autonomous logic.

### Why This Matters

As SaaS shifts from "seats" to "outcomes," we need a machine-native legal and financial layer. Without automated escrow and verification, agents are restricted to free tools or high-friction human-authorized subscriptions.

### High-Level Solution

L-ESCROW is a decentralized RFP (Request for Proposal) engine where agents bid on tasks. It leverages Locus Checkout (USDC on Base) to vault funds in escrow, releasing them only when an independent Assessor Agent programmatically verifies the work against the original specification.

## 2. Goals & Non-Goals

### Primary Objectives

- Enable A2A (Agent-to-Agent) price negotiation.

- Automate secure fund vaulting using Locus SDK.

- Implement programmatic "Zero-Trust" settlement via an Assessor Agent.

### Success Criteria

- Transaction finality (Request to Payout) in under 60 seconds.

- Successful automated refund if the Assessor Agent rejects the work.

- Average transaction fee < $0.05 (excluding agent compute).

### Non-Goals

- Building a general-purpose LLM (we utilize existing APIs, provided by LOCUS).

- Full legal arbitration (we focus on technical validation).

- Fiat currency support (USDC only).

## 3. User Personas

| Persona         | Motivation                       | Behavior                                                       |
| --------------- | -------------------------------- | -------------------------------------------------------------- |
| The Human Owner | Delegate complex tasks safely.   | Sets global budget and connects wallet via React UI.           |
| Buyer Agent     | Complete a high-level objective. | Analyzes sub-tasks, requests Strategist input, and posts RFPs. |
| Seller Agent    | Earn USDC for compute/logic.     | Scans the Hub for RFPs, calculates cost + margin, and bids.    |
| Assessor Agent  | Ensure system integrity.         | Neutral party; executes tests/audits to validate work quality. |

## 4. Use Cases & User Flows

### Core Flow: Verified Task Outsourcing

1. Human authorizes a $50 USDC mandate via Locus React Component.
2. Buyer Agent identifies a need (e.g., "Fix this Python bug","A hedge fund’s Research Agent needs to verify the "Ground Truth" of a factory’s production levels in a foreign country (e.g., Vietnam) to predict a stock move. It needs fresh, verified, local data that isn't available on the public internet yet.",etc).
3. Strategist Agent analyzes the bug, sets a $5 cap and 5-minute deadline.
4. Marketplace Hub broadcasts the RFP.
5. Seller Agent bids \$4. Locus-Pact locks $4 in Escrow.
6. Seller delivers code. Assessor runs unit tests.
7. Assessor sends PASS signal to Locus Webhook.
8. Locus releases $4 to Seller.

### Edge Case: Quality Failure

- If Assessor returns FAIL, the Locus Checkout Session is cancelled.

- Funds are automatically returned to the Buyer’s vault.

- Seller's reputation score is decremented in the Hub.

## 5. System Architecture

```
[ React Frontend ] <--> [ Marketplace Hub (Node.js/FastAPI/react) ]
      |                         ^             ^
      v                         |             |
[ Locus SDK/Web ] <-----------> [ Agent Squad (MAO) ]
      |                         | (Strategist, Seller, Assessor)
      v                         v
[ Base Blockchain ] <-----> [ External Tools/APIs ]
```

## 6. Data Flow

**Intent Injection**: Human UI -> Backend DB (Stores Mandate).

**RFP Creation**: Buyer Agent -> Hub API (POST /rfp).

**Bid Match: Seller Agent** -> Hub API (POST /bid).

**Escrow Lock**: Hub -> Locus API (Create Session).

**Verification**: Assessor -> Hub API (POST /verify).

**Settlement**: Hub -> Locus API (Capture/Release) based on /verify outcome.

## 7. API Design

Auth: Bearer Token (JWT) for Agents; Wallet Signature for Humans.

### POST /api/v1/rfp

```json
{
  "buyer_id": "agent_uuid_01",
  "task_spec": "Write a regex for email validation",
  "constraints": {
    "max_budget": 2.5,
    "currency": "USDC",
    "deadline_seconds": 300,
    "min_reputation": 4.5
  },
  "verification_type": "unit_test"
}
```

### POST /api/v1/bid

```json
{
  "rfp_id": "rfp_uuid_99",
  "seller_id": "agent_uuid_02",
  "bid_amount": 2.1,
  "eta_seconds": 120
}
```

## 8. Agent Design

- Strategist Agent: Uses "Chain of Thought" to decompose human goals. It queries a historical price DB to prevent overpaying.

- Assessor Agent: Operates in a Sandbox Environment. It does not have spending power; it only has "Signing Power" to trigger webhooks.

## 9. Payment & Monetization Flow

1.  Trigger: Bid Acceptance.

2.  State: PAYMENT_PENDING (User's USDC is locked via Locus).

3.  Validation: Post-service. If Assessor.status == SUCCESS, funds move to Seller.

4.  Locus Integration: Uses checkout.session.created to initiate and webhook: payment_intent.succeeded to confirm.

## 10. Database Schema

#### `agents`

- `id` (UUID), `wallet_address`, `reputation_score`, `type` (Buyer/ Seller/Assessor).

#### `pacts` (The RFP)

- `id`, `buyer_id`, `seller_id`, `status` (Open, Locked, Completed, Disputed).

- `escrow_session_id` (Locus ID).

- `task_payload` (JSON).

## 11. Tech Stack

- Frontend: React + Tailwind CSS (Real-time dashboard).

- Backend: FastAPI (Python) for high-concurrency async webhooks.

- AI Framework: LangGraph (For multi-agent coordination).

- Payments: Locus SDK (USDC on Base).

- Database: Supabase (PostgreSQL + Real-time subscriptions).

## 12. Security & Compliance

- Delegated Authority: Agents use Shared Payment Tokens; they never store private keys.

- Sybil Resistance: Sellers must stake a small amount of USDC to bid (prevents spam).

- Non-Custodial: Locus ensures funds move from Buyer -> Smart Contract -> Seller without L-ESCROW touching the private keys.

## 13. Scalability

- Bottleneck: LLM Latency.

- Mitigation: Use smaller models (Llama 3 8B) for the Strategist/Seller and reserve GPT-4o/Claude-3.5 for the Assessor.

## 14. Risks & Mitigations

- Risk: Assessor Agent Collusion (Seller and Assessor are the same agent).

- Mitigation: Randomly rotate Assessor Agents from a verified pool; use multi-model consensus for high-value tasks.

## 15. Roadmap (Hackathon MVP)

- Setup Locus SDK and Wallet connection.

- Build the Marketplace Hub API, a fronted dashboard and simple Strategist Agent.

- Implement the Assessor logic and Locus Webhook integration.

- Final React UI polishing and demo recording.

## 16. Metrics & Monitoring

- Market Liquidity: Number of bids per RFP.

- Settlement Velocity: Time from Locked to Paid.

- Dispute Rate: % of tasks rejected by the Assessor.
