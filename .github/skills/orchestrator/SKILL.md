# Orchestrator Skill

## Purpose

Single entry-point skill that drives the full QA pipeline end-to-end **inside Chainlit chat**. The same assistant runs each stage in order: read the stage skill, execute it, validate JSON, evaluate gates, and pass the full prior output into the next stage.

## When to Use

Invoke this skill when the user says any of:
- "Run the QA pipeline for {JIRA_KEY}"
- "Execute the full workflow for {JIRA_KEY}"
- "Start QA automation for {JIRA_KEY}"

## Prerequisites

| Requirement | How to Verify |
|---|---|
| `user-atlassian` MCP connected | Tool descriptors under `mcps/user-atlassian/tools/` |
| `user-qase` MCP connected | Tool descriptors under `mcps/user-qase/tools/` |
| `user-microsoft/playwright-mcp` connected | Tool descriptors under `mcps/user-microsoftplaywright-mcp/tools/` |
| `user-github` connected (recommended) | For Automation branch + PR and Healer follow-up pushes |
| Jira `cloudId` available | User provides or environment |
| Qase `project_code` available | User provides (e.g. "GPS") |

## Chainlit stage execution

For each stage below, **in the same Chainlit session**:

1. Open and follow the referenced `SKILL.md` and checklists.
2. Include the full JSON from the previous stage in your working context (stages after Planner).
3. Return or record only the structured JSON required by the agent definition before moving on.
4. **You** (orchestrator) evaluate decision gates; do not ask a sub-process to decide gates.

### Stage 1 — Planner

Work through the planner skill as the active step:

```
Read the skill file at `.github/skills/planner/SKILL.md` and follow it exactly.

Input:
- Jira Cloud ID: {cloudId}
- Jira Issue Key: {jiraKey}

Execute all steps (Jira Fetch -> Gap Analysis -> Decision Gate 1).
Read and follow the checklist at `.github/skills/planner/gap-analysis-checklist.md` for each step.

Return ONLY the structured JSON output defined in `.github/agents/planner.agent.md` Output Format section.
```

**Gate 1 — you evaluate:**
- Parse the returned JSON.
- If `status === "PROCEED"` and `gap_score >= threshold` (from config, default 2) -> continue to Environment Resolution.
- If `status === "STOP"` or `gap_score < threshold` -> report gap findings to the user and **STOP**.

### Environment Resolution (between Gate 1 and Stage 2)

After the Planner returns and Gate 1 passes, resolve URL and login credentials (same 3-tier logic as before):

**Tier 1 — Planner output `environment_details`**  
**Tier 2 — `tests/config/environments.ts`** (`TEST_ENV`, labels)  
**Tier 3 — Ask the user in Chainlit** for any missing `base_url`, `email`, or `password`.

Store `{baseURL}`, `{email}`, `{password}` for Stages 3-5.

### Stage 2 — Qase Designer

```
Read the skill file at `.github/skills/qase-designer/SKILL.md` and follow it exactly.

Input (Planner Agent output):
{paste full JSON from Stage 1}

Project code: {projectCode}

Execute all steps (Member Resolution -> Create Suite -> Design Cases -> Create Plan -> Feasibility -> Decision Gate 2).
Read and follow the checklists at:
- `.github/skills/qase-designer/test-design-checklist.md`
- `.github/skills/qase-designer/feasibility-checklist.md`

Return ONLY the structured JSON output defined in `.github/agents/qase-designer.agent.md` Output Format section.
```

**Gate 2 — you evaluate:**
- If `status === "PROCEED"` and `automatable_case_ids` is non-empty -> Stage 3.
- Else report manual-only and **STOP**.

### Stage 3 — Automation

> **Deriving `featureName`**: From Planner `summary` or Jira title; lowercase-hyphenated for folder names (e.g. "GPS Login" -> `gps-login`).

```
Read the skill file at `.github/skills/automation/SKILL.md` and follow it exactly.

Input (Qase Designer Agent output):
{paste full JSON from Stage 2}

Feature name: {featureName}
Base URL: {baseURL}

Write Playwright specs and page objects into this repository (see skill). **Use Playwright MCP** to inspect the real DOM before coding. Use the Base URL for DOM inspection in Step 2.
Then **push a feature branch to GitHub and open a PR** with those files (see Automation skill Step 6). Record `branch`, `pr_url`, `pr_number` in the JSON.
Read and follow the checklist at `.github/skills/automation/script-generation-checklist.md`.

Return ONLY the structured JSON output defined in `.github/agents/automation.agent.md` Output Format section.
```

No gate after this stage. Continue to Stage 4.

### Stage 4 — Executor

```
Read the skill file at `.github/skills/executor/SKILL.md` and follow it exactly.

Input (Automation Agent output):
{paste full JSON from Stage 3}

Automatable Case IDs (from Qase Designer — use ONLY these for create_run cases):
{paste automatable_case_ids array from Stage 2 output}

Project code: {projectCode}
Base URL: {baseURL}
Login email: {email}
Login password: {password}

Execute all steps (Member Resolution + Create Run -> Execute Tests -> Report Results -> Complete Run).
**First:** Check out Automation’s `git` **branch** in the repo (`git fetch` / `git checkout` / `git pull`) so you run the tests that were pushed for the PR.
Use the Base URL, login email, and password above for test execution.
Prefer **`npx playwright test`** on the spec paths from Automation when possible, in addition to or instead of pure MCP stepping — see executor skill.
Use ONLY the Automatable Case IDs listed above when calling create_run — pass them in the cases array. Do NOT use include_all_cases or plan_id.
Read and follow the checklist at `.github/skills/executor/execution-checklist.md`.

IMPORTANT: For step-level result reporting, use the Qase REST API directly (not the MCP create_result tool). See Step 3 in the skill file. Each Qase case step should receive a status and, when possible, **screenshot attachment(s)** on the step row (capture via Playwright MCP, upload per Qase attachment API, reference `hash` in the REST `steps[].attachments` payload).

**Non-negotiable:** Call Qase MCP **`create_run`** and use the returned numeric **`run_id`** in **`complete_run`** and in all result payloads. Never output placeholder run ids. Final user summary must include the real **`qase_run_id`** and **full repo-relative paths** to every generated spec and page object from the Automation JSON (`tests/...`).

Return ONLY the structured JSON output defined in `.github/agents/executor.agent.md` Output Format section.
```

**Failure check — you evaluate:**
- If `failures` is non-empty -> Stage 5.
- If empty -> pipeline success.

### Stage 5 — Healer (conditional)

```
Read the skill file at `.github/skills/healer/SKILL.md` and follow it exactly.

Input (Executor Agent output):
{paste full JSON from Stage 4}

Jira Cloud ID: {cloudId}
Jira Project Key: {jiraProjectKey}
Qase Project Code: {projectCode}

Execute all steps (Classify Failures -> Self-Heal -> Handle Data Issues -> Create Jira Defects -> Update Results).
For **self-heals**, **commit and push** fixes to the **same branch** Automation used (PR updates automatically). Use GitHub MCP or terminal git with `GITHUB_TOKEN` / `GH_PAT`.
Read and follow the checklist at `.github/skills/healer/failure-analysis-checklist.md`.

Return ONLY the structured JSON output defined in `.github/agents/healer.agent.md` Output Format section.
```

## Stage capabilities

| Stage | Primary needs |
|-------|----------------|
| 1 Planner | Atlassian MCP |
| 2 Qase Designer | Qase MCP; Atlassian for story context |
| 3 Automation | Qase MCP, Playwright MCP, GitHub MCP, workspace file writes |
| 4 Executor | Qase MCP, Playwright MCP, git checkout + Playwright CLI |
| 5 Healer | Atlassian, Qase, Playwright MCP, GitHub MCP, workspace file edits |

## Critical Rules

1. **Decision gates run in the orchestrator** — same chat session, not delegated.
2. **Validate JSON** between stages per `.github/rules/agent-output.md`.
3. **Pass full prior JSON** into each stage prompt/context.
4. **Sequential only** — no parallel stages.
5. **Skill-first** — each stage begins by reading its `SKILL.md`.
6. **Chainlit scope** — see `.github/rules/chainlit-scope.md` (chat-driven stages; GitHub **MCP** for branch/PR is in scope; CI runners are not assumed).

## Final Summary Output

After completion (or early stop), summarize for the user. Omit sections for stages that did not run.

**Full pipeline example:**

```json
{
  "pipeline": "complete",
  "jira_key": "PROJ-123",
  "stages_completed": ["planner", "qase-designer", "automation", "executor", "healer"],
  "gate1": { "score": 5, "result": "PROCEED" },
  "gate2": { "automatable_count": 8, "manual_count": 2, "result": "PROCEED" },
  "test_run": {
    "run_id": 789,
    "total": 8,
    "passed": 6,
    "failed": 2,
    "pass_rate": "75%"
  },
  "healing": {
    "self_healed": 1,
    "defects_created": 1,
    "data_corrections_needed": 0
  },
  "artifacts": {
    "qase_plan_id": 456,
    "qase_run_id": 789,
    "test_paths": ["tests/fulfillment-cart-duplicate/tc-366-slug.spec.ts"],
    "page_object_paths": ["tests/pages/fulfillmentCart.page.ts"],
    "jira_defects": ["PROJ-456"]
  }
}
```

**Stopped at Gate 1:**

```json
{
  "pipeline": "stopped_at_gate1",
  "jira_key": "PROJ-123",
  "stages_completed": ["planner"],
  "gate1": { "score": 3, "result": "STOP", "gap_report": "..." }
}
```

**Stopped at Gate 2:**

```json
{
  "pipeline": "stopped_at_gate2",
  "jira_key": "PROJ-123",
  "stages_completed": ["planner", "qase-designer"],
  "gate1": { "score": 5, "result": "PROCEED" },
  "gate2": { "automatable_count": 0, "manual_count": 10, "result": "STOP" }
}
```
