# AE QA Agentic · Human-in-the-loop

![A+E Global Media](/public/ae-logo.svg)

> **Initiative:** Agentic end-to-end QA inside a single chat — **Planner → Qase design → Automation → Executor → Healer** — with **MCP** (Atlassian/Jira, Qase, Playwright) and human approval where skills require it. The **A+E Global Media** logo above matches the header wordmark in Chainlit.

## Before you start

1. Connect MCP servers from the **plug** menu (Atlassian, Qase, Playwright as needed).
2. Open **Chat settings** (gear / sidebar) to choose the **OpenAI model** and **Skill pack** (orchestrator, planner, automation, etc.).
3. Ensure `OPENAI_API_KEY` (and any product URLs or tokens) are set in `.env`, then restart Chainlit.

## Useful links

- [Chainlit documentation](https://docs.chainlit.io)
- Repo: **AE.QA.Agentic** — see `README.md` and `.github/AGENTS.md` for agent scope

---

*Welcome screen: edit `chainlit.md`. Theme: `public/theme.json`. Extra styles: `public/custom.css`.*
