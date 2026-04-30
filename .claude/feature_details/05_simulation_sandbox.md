## Simulation Sandbox (The World)

## Overview

Phase 1 establishes the Simulation Sandbox, a local "Mock-Git" environment that replicates the lifecycle of a software repository. Instead of interacting with the real GitHub API (which is slow and requires complex auth), agents will perform file operations—cloning, editing, and merging—within a controlled directory structure. This enables a high-velocity, 15-agent demo where code is visibly "fixed" in real-time.

### 1. Sandbox Architecture

The infrastructure consists of three primary data stores located in backend/simulation_sandbox/:

- `/repo` (The Source of Truth): Contains the current state of the "production" code. This code starts "broken" (seeded with intentional bugs).

- `/prs` (The Staging Area): Where Seller Agents "push" their proposed fixes. Files are named using the pattern pr*{agent_id}*{rfp_id}.py.

- `issues.json` (The Issue Tracker): A JSON database containing the backlog of bugs. Each entry serves as the trigger for a Buyer Agent's RFP.

### 2. The Simulation Manager (`SimulationManager`)

We will implement a central utility class to govern the "physics" of this world.
Core Utilities:

- `reset_sandbox()`: Clears all PRs and restores the repo/ directory to its original "broken" state from a hidden template folder. (Critical for repeatable demos).

- `get_unresolved_issues()`: Returns issues from issues.json that do not have a corresponding Completed pact in the DB.

- `merge_fix(rfp_id)`: Triggered by a PASS verdict from the Assessor. It copies the file from `/prs` to `/repo`, effectively "fixing" the production code.

### 3. Seed Scenarios (The Demo Backlog)

To populate the marketplace, we will seed the sandbox with three distinct scenarios:

| Scenario      | File          | The Bug                                                  | Bounty  |
| ------------- | ------------- | -------------------------------------------------------- | ------- |
| Logic Error   | math_utils.py | A divide function that doesn't handle ZeroDivisionError. | 20 USDC |
| Security Risk | auth.py       | A hardcoded admin password ADMIN_1234.                   | 50 USDC |
| Syntax Error  | client.py     | A missing closing parenthesis on a dictionary.           | 10 USDC |

### 4. Technical Specifications

**File Operations Logic:**

1. Read: Agents use `pathlib` to read file contents into their LLM context.

2. Write: Seller Agents write their output directly to the `/prs` directory.

3. Diffing: The Assessor Agent reads both the original in `/repo`and the proposed fix in `/prs` to generate a text-based diff for the Jury to review.

**LangGraph Integration:**

    State Updates: The `AssessorState` will now include `original_code` and `proposed_code` strings.

    Environment Variables: `SIMULATION_PATH` will point to the absolute path of the sandbox.

5. Definition of Done (Phase 1)

   [ ] `backend/simulation_sandbox/` directory structure is created and added to `.gitignore` (except for seed files).

   [ ] `issues.json` contains at least 3 valid bug scenarios.

   [ ] `SimulationManager.reset_sandbox()` successfully restores the repo to its broken state.

   [ ] The Buyer Agent can successfully parse `issues.json` and generate an RFP for each entry.

   [ ] A manual file copy from `/prs` to `/repo` via `merge_fix()` is functional.
