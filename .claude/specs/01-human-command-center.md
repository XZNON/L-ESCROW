# Spec: Human Command Center and Policy Mandate

## Overview

This feature establishes the L-ESCROW Command Center, the primary human-to-agent interface. It exists to solve the "delegated authority" problem: allowing a human to connect a wallet via the Locus React Component and define a "Policy Mandate" (spending limits and verification rules) that the Buyer Agent must follow when posting RFPs.

---

## Depends on

- Initial project scaffolding (Step 00)
- Locus SDK Environment Variables (API Keys/Base Network config)
- Your can find the skill related to Locus SDK at @C:\Users\XZNON\.locus\skills\SKILL.md

---

## Routes

- GET / — Dashboard overview showing agent balance and active pacts — (Public/Owner)
- GET /settings — Interface to set spending mandates and connect wallet — (Owner)
- POST /api/v1/mandate — API endpoint to save the Locus Shared Payment Token and policy rules — (Logged-in)
- GET /api/v1/balance — Fetches current USDC balance from the Locus-linked wallet — (Logged-in)

---

## Database changes

- Table: users (or owner): Add locus_auth_token (Text), max_task_budget (Float), and daily_limit (Float).
- Table: agent_policies: New table to store specific constraints (e.g., required_assessor_score, allowed_service_types).

---

## Templates

- Create: templates/dashboard.html — The "Pulse" feed of agent activity.
- Create: templates/settings.html — Wallet connection and mandate configuration.
- Modify: templates/base.html — Include Locus SDK script tags and navigation links.

---

## Files to change

- app.py — Registering dashboard and settings routes.
- database/db.py — Adding functions to update user mandates and store Locus tokens.
- CLAUDE.md — Marking Step 01 as in-progress/complete.

---

## Files to create

- .claude/specs/01-human-command-center.md — This specification file.
- static/css/dashboard.css — Custom styles for the agent activity feed.
- static/js/locus-integration.js — Client-side logic for the Locus React/JS component.

---

## New dependencies

- locus-sdk (or the specific JS/Python package for Locus integration)
- requests (for backend-to-Locus API communication)

---

## Rules for implementation

- No SQLAlchemy or ORMs.
- Parameterised queries only for storing tokens/mandates.
- Passwords (if used for dashboard access) hashed with werkzeug.
- Use CSS variables for the dashboard "Status" colors (e.g., --color-escrow-locked).
- All templates extend base.html.
- Locus Specific: Never store the raw Wallet Private Key; only store the Shared Payment Token returned by the Locus auth flow.

---

## Definition of done

- [ ] User can successfully connect a wallet via the UI.
- [ ] User can save a "Max Budget" (e.g., 10 USDC) to the database.
- [ ] The Dashboard displays a "Wallet Connected" status with the correct USDC balance.
- [ ] The settings page correctly persists policy rules to database/db.py.

---

**Branch:** feature/human-command-center  
**Spec file:** .claude/specs/01-human-command-center.md  
**Title:** Human Command Center and Policy Mandate
