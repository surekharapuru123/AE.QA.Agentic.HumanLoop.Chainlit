# Chainlit workflow scope

Skills, agent definitions, and checklists under `.github/` describe how the assistant behaves **inside the Chainlit app** (`chainlit run app.py`) with MCP tools (Atlassian, Qase, Playwright, **GitHub**) and workspace edits.

- Run stages **in order in the same chat session**, passing structured JSON between stages as defined in `.github/rules/agent-output.md`.
- **Do not** assume GitHub Actions, `repository_dispatch`, or `scripts/ci/run-agent.ts` as the execution runtime — the chat session drives stages; Actions may still run separately in a dev repo.
- **GitHub MCP** (`user-github`): used in **Automation** to push a **feature branch** and open a **PR**; **Executor** runs from that branch; **Healer** pushes fixes to the same branch so the PR updates. If GitHub is disconnected, stages may still write files locally but must record that in JSON.

When editing behaviors, update the skill and checklist first, then the agent definition if the output schema changes.
