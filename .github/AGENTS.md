# AE.QA.Agentic - Agent instructions (Chainlit)

## Project overview

This repo delivers an agent-based E2E QA flow: planning, Qase design, automation authoring, execution, and healing. The **supported runtime is Chainlit chat** with MCP-backed tools.

## Quick start — Chainlit

From the repo root (see `requirements.txt`):

```bash
pip install -r requirements.txt   # or: npm run setup:python
chainlit run app.py # or: npm run chainlit
```

Use **`npm run chainlit:watch`** to restart the app on code changes. Starter shortcuts for pipeline / single-stage prompts appear on a new thread in the Chainlit UI.

**MCP connectivity:** In chat, send **`/mcp-setup`** (or the starter **MCP setup probe**) to run one minimal `call_tool` per connected server (Qase `list_projects`, GitHub `get_me`, Atlassian `atlassianUserInfo` / `getAccessibleAtlassianResources`, Playwright `browser_tabs` list) without calling OpenAI. See also `npm run mcp:setup` for a terminal reminder.

In the Chainlit UI, connect MCP servers (plug icon): **Atlassian/Jira** (`node chainlit-atlassian-mcp.cjs`), **GitHub Copilot MCP** (`node chainlit-github-mcp.cjs` with `GITHUB_MCP_AUTHORIZATION` or `GITHUB_TOKEN` in `.env`), **Qase**, and **Playwright**. Add `OPENAI_API_KEY` to `.env` (see `.env.example`).

To drive the full pipeline in chat, the assistant follows:

```
.github/skills/orchestrator/SKILL.md
```

Example user request: "Run the QA pipeline for PROJ-123".

## MCP servers (Chainlit)

| Server | Identifier | Purpose |
|--------|-----------|---------|
| Atlassian (Jira) | `user-atlassian` | Stories, defects, gap context |
| Qase | `user-qase` | Cases, plans, runs, results, defects |
| Playwright | `user-microsoft/playwright-mcp` | Browser automation and DOM inspection |
| GitHub | `user-github` (typical id) | Feature branch + PR for Automation; Healer pushes fixes to the same branch |

Automation **inspects the live DOM with Playwright MCP**, **writes** tests under `tests/`, **pushes** a **feature branch**, and opens a **PR**. Executor **checks out** that branch to run tests. Healer **commits** locator/timing fixes to the **same branch** so the PR reflects updated code.

## Agent workflow (sequential pipeline)

```
Orchestrator (same Chainlit session)
  |
  +-- Stage 1: Planner
  |     +-- Gate 1: gap_score >= threshold (default 2)
  |           +-- STOP: gap report, end
  |           +-- PROCEED: environment resolution (Jira -> config -> ask user)
  +-- Stage 2: Qase Designer
  |     +-- Gate 2: at least one automatable case
  |           +-- STOP: manual-only, end
  |           +-- PROCEED
  +-- Stage 3: Automation (Playwright MCP DOM → specs/POM → push branch + PR)
  +-- Stage 4: Executor (checkout branch → run Playwright + Qase results)
  |     +-- Failures? -> Stage 5 Healer; else done
  +-- Stage 5: Healer (fix scripts → push to same branch / update PR)
```

## Agents and skills

| Stage | Agent definition | Skill | MCP / tools |
|-------|------------------|-------|-------------|
| Orchestrator | — | `.github/skills/orchestrator/SKILL.md` | Coordinates stages in chat |
| Planner | `.github/agents/planner.agent.md` | `.github/skills/planner/SKILL.md` | Atlassian (read) |
| Qase Designer | `.github/agents/qase-designer.agent.md` | `.github/skills/qase-designer/SKILL.md` | Atlassian (fallback), Qase |
| Automation | `.github/agents/automation.agent.md` | `.github/skills/automation/SKILL.md` | Qase (read), Playwright, GitHub, workspace files |
| Executor | `.github/agents/executor.agent.md` | `.github/skills/executor/SKILL.md` | Qase, Playwright, git checkout |
| Healer | `.github/agents/healer.agent.md` | `.github/skills/healer/SKILL.md` | Atlassian, Qase, Playwright, GitHub, workspace files |

## Shared rules

| Rule | File | Purpose |
|------|------|---------|
| MCP usage | `.github/rules/mcp-usage.md` | Tool expectations per agent |
| QA workflow | `.github/rules/qa-workflow.md` | Order, gates, naming |
| Test generation | `.github/rules/test-generation.md` | Playwright / POM standards |
| Agent output | `.github/rules/agent-output.md` | JSON between stages |
| Chainlit scope | `.github/rules/chainlit-scope.md` | In-scope runtime (Chainlit only) |

## Decision gates

Gates are evaluated by the **orchestrator** (the same assistant following the orchestrator skill), not delegated to a separate process.

## Environment resolution (URL and credentials)

| Priority | Source |
|----------|--------|
| 1 | Planner `environment_details` from Jira |
| 2 | `tests/config/environments.ts` matched by `TEST_ENV` or labels |
| 3 | Ask the user in Chainlit for any missing fields |

## In-chat execution model

1. **Sequential** — complete each stage and validate JSON before the next.
2. **Skill-first** — for each stage, read the listed `SKILL.md` and checklists.
3. **Full context** — paste the previous stage's JSON into the working context for the next stage.
4. **Resumable** — if a stage fails, repeat that stage using the last good upstream JSON.

## Member assignment (Qase)

Resolve and record the executing member (`list_authors`, `get_author`) before creating cases or runs, and echo identity in results comments as required by each skill.

## Conventions

- Structured JSON handoff per `.github/rules/agent-output.md`.
- POM and specs per `.github/rules/test-generation.md`.
- Test plan naming: `{FeatureName}_QA_Automation`.
- Jira defect summary prefix: `[Auto-Defect] {description}`.
