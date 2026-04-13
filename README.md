# AE.QA.Agentic

Agent-based End-to-End QA Automation Framework powered by Cursor AI, MCP servers, and GitHub Actions.

## Overview

This framework orchestrates the complete QA lifecycle — from Jira story analysis through test execution and defect reporting — using 5 specialized AI agents that run as Cursor subagents. A parent **Orchestrator** launches each agent sequentially, evaluates decision gates between stages, and passes structured JSON between them.

| # | Agent | What it does |
|---|-------|-------------|
| 1 | **Planner** | Fetches Jira stories, extracts requirements, performs gap analysis |
| 2 | **Qase Designer** | Generates test cases in Qase, creates test plans, assesses automation feasibility |
| 3 | **Automation** | Generates Playwright scripts (TypeScript, Page Object Model), pushes to Git, opens a PR |
| 4 | **Executor** | Creates test runs in Qase, executes tests via Playwright browser, reports step-level results |
| 5 | **Healer** | Classifies failures, self-heals selector/timing issues, creates Jira defects for real bugs |

## Quick Start

```
"Run the QA pipeline for PROJ-123"
```

That single prompt in Cursor triggers the orchestrator, which reads `.github/skills/orchestrator/SKILL.md` and drives the entire pipeline end-to-end.

## Prerequisites

- [Node.js](https://nodejs.org/) >= 18
- [Cursor IDE](https://cursor.sh/) with MCP servers configured
- MCP Servers: Atlassian, Qase, GitHub, Playwright

```bash
npm install
npx playwright install
```

## MCP Server Configuration

Ensure these MCP servers are enabled in Cursor:

| Server | Config Key | Purpose |
|--------|-----------|---------|
| Atlassian | `user-atlassian` | Jira read/write |
| Qase | `user-qase` | Test case management |
| GitHub | `user-github` | Repository operations |
| Playwright | `user-microsoft/playwright-mcp` | Browser automation |

### Playwright MCP — why you might not see a browser window

Automation and Executor drive a real Chromium (or other) instance **only when** the model calls Playwright MCP tools (`browser_navigate`, etc.). If Stage 4 only prints a summary and never shows **Used · … · browser_** steps in Chainlit, execution was skipped.

When tools **are** called, the window is **hidden** if the MCP server was started with **`--headless`** or **`PLAYWRIGHT_MCP_HEADLESS=1`**. For a **visible** browser:

- In **Cursor / Chainlit MCP settings**, remove `--headless` from the Playwright MCP command args, and set env **`PLAYWRIGHT_MCP_HEADLESS=false`** (or unset it) on that server.
- If Chainlit stdio MCP inherits this repo’s `.env`, you can set the same variable there and use **`CHAINLIT_MCP_FULL_ENV=1`** so the child process sees it.

Running **`npm run test`** / **`npx playwright test`** from a terminal uses **`playwright.config.ts`** (headless by default). Use **`npm run test:headed`** or **`npx playwright test --headed`** to see that run in a window — that path is separate from MCP.

### Chainlit UI — Setup starters

If you run the local Chainlit app (`chainlit run app.py`), the **Setup** starter **OpenAI / LLM check** runs **Step 1** (API ping), **skips Step 2** (no MCP tool list is sent to the model), then **Step 3** calls the model **without tools** so it cannot invoke Jira/GitHub or read remote `.env`. That isolates **OpenAI key + network** from MCP. To verify MCP servers, use **`/mcp-setup`** or the **MCP plug + Playwright** / **MCP probe** starters.

---

## How Agents, Skills, and Rules Work Together

Everything lives under `.github/`. Here is how the four building blocks relate:

```
.github/
├── AGENTS.md                  ← Workspace instructions (Cursor auto-loads this)
├── agents/                    ← Agent definitions (the "who" — identity + step-by-step instructions)
│   ├── planner.agent.md
│   ├── qase-designer.agent.md
│   ├── automation.agent.md
│   ├── executor.agent.md
│   └── healer.agent.md
├── skills/                    ← Skills (the "how" — detailed procedures + checklists)
│   ├── orchestrator/
│   │   └── SKILL.md
│   ├── planner/
│   │   ├── SKILL.md
│   │   └── gap-analysis-checklist.md
│   ├── qase-designer/
│   │   ├── SKILL.md
│   │   ├── test-design-checklist.md
│   │   └── feasibility-checklist.md
│   ├── automation/
│   │   ├── SKILL.md
│   │   └── script-generation-checklist.md
│   ├── executor/
│   │   ├── SKILL.md
│   │   └── execution-checklist.md
│   └── healer/
│       ├── SKILL.md
│       └── failure-analysis-checklist.md
├── rules/                     ← Shared rules (the "what standards" — cross-cutting constraints)
│   ├── mcp-usage.md
│   ├── qa-workflow.md
│   ├── agent-output.md
│   └── test-generation.md
├── workflows/                 ← GitHub Actions CI/CD
│   ├── e2e-qa-pipeline.yml
│   └── test-on-pr.yml
└── workflow-templates/        ← Workflow templates for dev repos to copy
    └── trigger-qa-from-dev-pr.yml
```

### AGENTS.md — Workspace Instructions

`.github/AGENTS.md` is auto-loaded by Cursor for every conversation. It provides:
- The list of all agents and their MCP tool mappings
- The pipeline order and decision gate thresholds
- Pointers to skills, rules, and agent definitions
- Shared conventions (naming, output schema, member assignment)

### Agent Definitions (`.agent.md`)

Each file in `.github/agents/` defines **one agent's identity and step-by-step instructions**. Think of it as a persona card: who the agent is, what MCP servers it uses, what steps it follows, and what JSON output it must produce.

When the orchestrator launches a subagent, it tells it to read its `.agent.md` file and the corresponding `SKILL.md`.

### Skills (`SKILL.md` + checklists)

Each folder in `.github/skills/` contains a `SKILL.md` with the full operational procedure and one or more checklists. Skills are the **detailed playbook** the agent follows step-by-step. Checklists ensure no step is skipped.

| Component | Role |
|-----------|------|
| `SKILL.md` | Complete procedure with MCP tool calls, input/output contracts, and gate logic |
| `*-checklist.md` | Step verification — agent reads this before/after each step to confirm completeness |

### Shared Rules

Files in `.github/rules/` define **cross-cutting standards** that apply to multiple agents:

| Rule | Who uses it | What it enforces |
|------|------------|-----------------|
| `mcp-usage.md` | All agents | Which MCP server/tool each agent may call, required parameters |
| `qa-workflow.md` | All agents | Pipeline order, decision gate thresholds, naming conventions |
| `agent-output.md` | Orchestrator | JSON schema each agent must produce for inter-stage handoff |
| `test-generation.md` | Automation Agent | Playwright/POM coding standards, selector priority, test structure |

---

## Complete QA Pipeline Flow

Here is exactly what happens when you say **"Run the QA pipeline for PROJ-123"**:

### 1. Orchestrator Starts

The orchestrator (parent agent) reads `.github/skills/orchestrator/SKILL.md` which contains the full pipeline recipe. It then launches each stage as an isolated Cursor subagent.

### 2. Stage 1 — Planner

```
Orchestrator launches subagent (Task tool, type: generalPurpose)
  │
  ├─ Subagent reads:
  │   ├── .github/skills/planner/SKILL.md         (procedure)
  │   ├── .github/skills/planner/gap-analysis-checklist.md  (verification)
  │   └── .github/agents/planner.agent.md          (identity + output format)
  │
  ├─ Calls MCP: user-atlassian
  │   ├── getJiraIssue → fetch the story
  │   └── searchJiraIssuesUsingJql → fetch linked issues
  │
  ├─ Performs gap analysis (scores 5 areas 0–1, total 0–5)
  │
  └─ Returns JSON: { agent, jira_key, status, gap_score, summary, acceptance_criteria, ... }
```

**Decision Gate 1** (evaluated by orchestrator):
- `gap_score >= threshold` (configurable, default 2) → PROCEED to Stage 2
- `gap_score < threshold` → STOP, report gap findings

### 3. Stage 2 — Qase Designer

```
Orchestrator passes Planner JSON → launches subagent
  │
  ├─ Subagent reads:
  │   ├── .github/skills/qase-designer/SKILL.md
  │   ├── .github/skills/qase-designer/test-design-checklist.md
  │   ├── .github/skills/qase-designer/feasibility-checklist.md
  │   └── .github/agents/qase-designer.agent.md
  │
  ├─ Calls MCP: user-qase
  │   ├── list_authors → resolve member identity
  │   ├── create_suite → create test suite
  │   ├── create_case (×N) → create test cases
  │   ├── create_plan → create test plan
  │   └── update_case (×N) → set automation feasibility
  │
  └─ Returns JSON: { agent, status, project_code, suite_id, plan_id, test_cases[], automatable_case_ids[], ... }
```

**Decision Gate 2** (evaluated by orchestrator):
- `automatable_case_ids` non-empty → PROCEED to Stage 3
- All cases manual → STOP

### 4. Stage 3 — Automation

```
Orchestrator passes Qase Designer JSON → launches subagent
  │
  ├─ Subagent reads:
  │   ├── .github/skills/automation/SKILL.md
  │   ├── .github/skills/automation/script-generation-checklist.md
  │   ├── .github/agents/automation.agent.md
  │   └── .github/rules/test-generation.md          (coding standards)
  │
  ├─ Calls MCP: user-qase
  │   └── get_case (×N) → fetch full test case details
  │
  ├─ Generates Playwright scripts following Page Object Model
  │
  ├─ Calls MCP: user-github
  │   ├── create_branch → feature/automation-{name}
  │   ├── push_files → commit all scripts
  │   └── create_pull_request → open PR
  │
  └─ Returns JSON: { agent, status, branch, pr_url, scripts[], total_scripts, ... }
```

No decision gate — proceeds directly to Stage 4.

### 5. Stage 4 — Executor

```
Orchestrator passes Automation JSON → launches subagent
  │
  ├─ Subagent reads:
  │   ├── .github/skills/executor/SKILL.md
  │   ├── .github/skills/executor/execution-checklist.md
  │   └── .github/agents/executor.agent.md
  │
  ├─ Calls MCP: user-qase
  │   ├── list_authors → resolve executor identity
  │   ├── create_run → create test run
  │   ├── get_case (×N) → fetch step definitions
  │   └── complete_run → finalize
  │
  ├─ Calls MCP: user-microsoft/playwright-mcp
  │   ├── browser_navigate, browser_click, browser_type → execute test steps
  │   ├── browser_take_screenshot → capture every step
  │   └── browser_console_messages → capture diagnostics on failure
  │
  ├─ Reports results via Qase REST API (step-level with screenshots)
  │
  └─ Returns JSON: { agent, status, run_id, executed_by, summary, failures[], ... }
```

**Failure Check** (evaluated by orchestrator):
- `failures[]` non-empty → proceed to Stage 5
- `failures[]` empty → pipeline complete

### 6. Stage 5 — Healer (conditional)

```
Orchestrator passes Executor JSON → launches subagent
  │
  ├─ Subagent reads:
  │   ├── .github/skills/healer/SKILL.md
  │   ├── .github/skills/healer/failure-analysis-checklist.md
  │   └── .github/agents/healer.agent.md
  │
  ├─ Classifies each failure:
  │   ├── Script issue → self-heal (update selector, add wait, re-run)
  │   ├── Data issue → flag DATA_CORRECTION_NEEDED (no retry)
  │   ├── Functional defect → create Jira bug + Qase defect
  │   └── Environment issue → log and report
  │
  ├─ Calls MCP: user-microsoft/playwright-mcp (re-inspect DOM for self-healing)
  ├─ Calls MCP: user-atlassian (createJiraIssue for real bugs)
  ├─ Calls MCP: user-qase (create_defect, update results)
  │
  └─ Returns JSON: { agent, status, actions[], summary: { self_healed, defects_created, ... } }
```

### 7. Pipeline Summary

The orchestrator collects all stage outputs and produces a final summary:

```json
{
  "pipeline": "complete",
  "jira_key": "PROJ-123",
  "stages_completed": ["planner", "qase-designer", "automation", "executor", "healer"],
  "gate1": { "score": 5, "result": "PROCEED" },
  "gate2": { "automatable_count": 8, "result": "PROCEED" },
  "test_run": { "run_id": 789, "passed": 6, "failed": 2, "pass_rate": "75%" },
  "healing": { "self_healed": 1, "defects_created": 1 },
  "artifacts": {
    "qase_plan_id": 456,
    "qase_run_id": 789,
    "github_pr_url": "https://github.com/org/repo/pull/42",
    "jira_defects": ["PROJ-456"]
  }
}
```

---

## How Files Call Each Other (Reference Map)

```
User prompt
  └─ Orchestrator (parent agent)
       ├── reads .github/AGENTS.md                    (auto-loaded by Cursor)
       ├── reads .github/skills/orchestrator/SKILL.md (pipeline recipe)
       ├── reads .github/rules/agent-output.md        (validates each stage's JSON)
       │
       └── for each stage, launches a subagent that:
             ├── reads .github/agents/{name}.agent.md     (identity + steps)
             ├── reads .github/skills/{name}/SKILL.md     (detailed procedure)
             ├── reads .github/skills/{name}/*-checklist.md (step verification)
             ├── reads .github/rules/mcp-usage.md          (tool schemas)
             └── calls MCP tools (Atlassian, Qase, GitHub, Playwright)
```

## Running Individual Agents

You can run any agent independently by providing the required input JSON:

| Command | What it does |
|---------|-------------|
| "Run the planner for PROJ-123" | Runs Stage 1 only |
| "Design test cases from this planner output: `{json}`" | Runs Stage 2 with provided input |
| "Generate automation scripts from this designer output: `{json}`" | Runs Stage 3 |
| "Execute tests from this automation output: `{json}`" | Runs Stage 4 |
| "Heal failures from this executor output: `{json}`" | Runs Stage 5 |

## CI Pipeline (GitHub Actions)

The same 5-stage AI pipeline that runs in Cursor can also run in GitHub Actions, triggered automatically from a dev repo PR linked to a Jira ticket.

### How It Works

```
Developer Repo                          AE.QA.Agentic Repo
┌─────────────────────┐                ┌──────────────────────────────────┐
│ PR opened/updated   │                │  e2e-qa-pipeline.yml             │
│ title: "TA-1607:    │  repository    │                                  │
│   Fix login flow"   │──dispatch───►  │  Stage 1: Planner (LLM + Jira)  │
│                     │                │       ↓ Gate 1: score=5?         │
│ trigger-qa-e2e.yml  │                │  Stage 2: Designer (LLM + Qase) │
│ ├─ Extract Jira ID  │                │       ↓ Gate 2: feasible?        │
│ ├─ Dispatch to QA   │                │  Stage 3: Automation (LLM + Git)│
│ └─ Confirm on PR    │                │       ↓                          │
│                     │   results      │  Stage 4: Executor (Playwright) │
│                     │◄──comment───── │       ↓ failures?                │
│                     │                │  Stage 5: Healer (LLM + Jira)   │
└─────────────────────┘                └──────────────────────────────────┘
```

Each stage uses `scripts/ci/run-agent.ts` which:
1. Loads the same agent definition + skill + checklists from `.github/`
2. Calls Claude API or OpenAI API for AI reasoning (configurable via `LLM_PROVIDER`)
3. Executes tool calls as direct REST API calls (Jira, Qase, GitHub, Playwright CLI)
4. Passes structured JSON output to the next stage via GitHub Actions artifacts

### Required Secrets (on AE.QA.Agentic Repo)

| Secret | Purpose |
|--------|---------|
| `ANTHROPIC_API_KEY` | Claude API key (if using Anthropic) |
| `OPENAI_API_KEY` | OpenAI API key (if using OpenAI) |
| `JIRA_API_TOKEN` | Jira API token (Basic auth) |
| `JIRA_EMAIL` | Jira user email (Basic auth) |
| `JIRA_CLOUD_ID` | Jira Cloud ID |
| `QASE_API_TOKEN` | Qase API token |
| `CROSS_REPO_TOKEN` | GitHub PAT for cross-repo operations |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams Incoming Webhook URL for QA result notifications |

### Required Secret (on Dev Repo)

| Secret | Purpose |
|--------|---------|
| `QA_DISPATCH_TOKEN` | GitHub PAT with repo scope on AE.QA.Agentic (for `repository_dispatch`) |

### Setup for Dev Teams

**1.** Create a GitHub PAT with **Contents: Read & Write** on the `AE.QA.Agentic` repo

**2.** Add it as `QA_DISPATCH_TOKEN` in your dev repo (Settings → Secrets → Actions)

**3.** Add `CROSS_REPO_TOKEN` on the Agentic repo (for cross-repo Git operations)

**4.** Set up Teams notification:
   - In your Teams channel, add an **Incoming Webhook** connector
   - Copy the webhook URL
   - Add it as `TEAMS_WEBHOOK_URL` in the Agentic repo (Settings → Secrets → Actions)

**5.** Copy `.github/workflow-templates/trigger-qa-from-dev-pr.yml` into your dev repo at:

```
your-dev-repo/.github/workflows/trigger-qa-e2e.yml
```

**6.** Update the configuration values:

| Variable | What to set |
|----------|------------|
| `QA_REPO` | `aenetworks-gto/AE.QA.Agentic` |
| `DEFAULT_QASE_PROJECT` | Qase project code (e.g., `GPS`) |
| `DEFAULT_BASE_URL` | QA environment URL |
| `LLM_PROVIDER` | `anthropic` or `openai` |

### Jira Key Detection

Extracts the Jira key from the PR in this priority order:

1. **PR title** — e.g., `TA-1607: Fix login timeout`
2. **Branch name** — e.g., `feature/TA-1607-fix-login`
3. **PR body** — any `PROJ-123` pattern in the description

If no Jira key is found, the pipeline is **not** triggered.

### Manual Trigger

From the Agentic repo's Actions tab, use `workflow_dispatch` with the Jira key, project code, base URL, and LLM provider.

---

## Run Tests Locally

```bash
npx playwright test
npx playwright test --project=chromium
npx playwright test --headed
```

## Further Reading

- [ARCHITECTURE.md](./ARCHITECTURE.md) — System design, subagent model, MCP integration map, data flow diagrams
