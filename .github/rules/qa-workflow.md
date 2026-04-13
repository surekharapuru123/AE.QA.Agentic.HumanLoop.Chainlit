# QA Workflow Rules

## Agent Execution Order
Agents MUST execute in this strict order:
1. Planner → 2. Qase Designer → 3. Automation → 4. Executor → 5. Healer

## Decision Gates
- Gate 1 (after Planner): Gap score MUST be at least 2 to proceed. Any score < 2 means STOP.
- Gate 2 (after Qase Designer): At least 1 test case MUST have feasibility score ≥ 1 to proceed.

## MCP Server Usage
- Atlassian (`user-atlassian`): Jira read (Planner) and Jira write (Healer)
- Qase (`user-qase`): Test cases, plans, runs, results, defects
- Playwright (`user-microsoft/playwright-mcp`): DOM inspection (Automation), execution (Executor), re-identification (Healer)
- GitHub (`user-github` or org-configured id): **Automation** pushes specs on a **feature branch** and opens a **PR**; **Executor** runs tests from that branch; **Healer** commits fixes to the **same branch** so the PR updates

## Agent Output
- Every agent MUST produce structured JSON output
- Output MUST include `agent`, `status`, and all fields defined in the agent's Output Format section
- The next agent in the pipeline consumes the previous agent's output

## Checklist Compliance
- Before completing any step, the agent MUST read its skill's checklist
- All checklist items MUST be addressed (checked or explicitly noted as not applicable)

## Naming Conventions
- Test suites: `{FeatureName}_Test_Suite`
- Test plans: `{FeatureName}_QA_Automation`
- Local feature folder under `tests/`: match feature slug (e.g. `tests/{feature-name}/`)
- Jira defects: `[Auto-Defect] {description}`

## Workspace layout
- Automation writes specs under `tests/{feature}/` and page objects under `tests/pages/`, then **pushes** them on a dedicated **git branch** with a **pull request**
- Executor **checks out** that branch before running Playwright (CLI and/or MCP)
- Healer edits the same paths and **pushes** follow-up commits to the **same branch** (PR reflects changes automatically)
