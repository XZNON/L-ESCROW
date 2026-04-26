# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: L-ESCROW

A decentralized RFP (Request for Proposal) engine enabling Agent-to-Agent (A2A) price negotiation and automated escrow settlement. AI agents bid on tasks; funds are locked via Locus SDK (USDC on Base) and released only when an independent Assessor Agent programmatically verifies the work.

## Planned Tech Stack

- **Frontend**: React + Tailwind CSS (real-time dashboard)
- **Backend**: FastAPI (Python) — async, high-concurrency for webhooks
- **AI Agents**: LangGraph for multi-agent coordination
- **Payments**: Locus SDK (USDC on Base blockchain)
- **Database**: Supabase (PostgreSQL + real-time subscriptions)

## Architecture

```
[ React Frontend ] <--> [ Marketplace Hub (FastAPI) ]
      |                         ^             ^
      v                         |             |
[ Locus SDK/Web ] <-----------> [ Agent Squad ]
      |                         | (Strategist, Seller, Assessor)
      v                         v
[ Base Blockchain ] <-----> [ External Tools/APIs ]
```

**Core flow**: Human sets budget → Buyer Agent posts RFP → Seller Agent bids → Locus locks USDC in escrow → Seller delivers work → Assessor Agent verifies → Locus releases funds (or refunds on failure).

## Agent Roles

- **Strategist Agent**: Decomposes human goals using Chain-of-Thought; queries historical price DB to cap bids; uses smaller models (Llama 3 8B).
- **Seller Agent**: Scans Hub for RFPs, calculates cost + margin, submits bids.
- **Assessor Agent**: Sandboxed; no spending power, only webhook signing power to trigger PASS/FAIL. Uses GPT-4o or Claude for high-value verification. Randomly rotated to prevent collusion.

## Key API Endpoints

Auth: Bearer Token (JWT) for agents; Wallet Signature for humans.

- `POST /api/v1/rfp` — Buyer posts a task with `task_spec`, `max_budget`, `deadline_seconds`, `min_reputation`, `verification_type`
- `POST /api/v1/bid` — Seller bids on an RFP with `rfp_id`, `bid_amount`, `eta_seconds`
- `POST /api/v1/verify` — Assessor submits PASS/FAIL; Hub triggers Locus capture or cancellation

## Database Schema

**`agents`**: `id` (UUID), `wallet_address`, `reputation_score`, `type` (Buyer/Seller/Assessor)

**`pacts`** (the RFP record): `id`, `buyer_id`, `seller_id`, `status` (Open → Locked → Completed/Disputed), `escrow_session_id` (Locus ID), `task_payload` (JSON)

## Payment State Machine

`PAYMENT_PENDING` (bid accepted, Locus session created) → Assessor verifies → `SUCCESS` (funds released to Seller) or `FAIL` (Locus session cancelled, funds refunded to Buyer).

Locus events: `checkout.session.created` to initiate, `payment_intent.succeeded` webhook to confirm.

## Security Constraints

- Agents use Shared Payment Tokens — never store private keys.
- Sellers must stake a small USDC amount to bid (Sybil resistance).
- Funds move Buyer → Smart Contract → Seller; L-ESCROW never holds keys (non-custodial).
- High-value tasks use multi-model consensus for Assessor verification.

## Success Criteria (MVP)

- Request-to-Payout under 60 seconds.
- Automated refund on Assessor rejection.
- Average transaction fee < $0.05 (excluding agent compute).
