# MCP Usage Rules

## Server-Tool Mapping

### user-atlassian (Jira)
Read operations (Planner Agent + Qase Designer fallback):
- `getJiraIssue` - Requires: cloudId, issueIdOrKey
- `searchJiraIssuesUsingJql` - Requires: cloudId, jql

Write operations (Healer Agent):
- `createJiraIssue` - Requires: cloudId, projectKey, issueTypeName, summary
- `addCommentToJiraIssue` - Requires: cloudId, issueIdOrKey, body
- `editJiraIssue` - Requires: cloudId, issueIdOrKey, fields

### user-qase (Test Management)
Test cases (Qase Designer + Automation):
- `create_case` - Requires: code, title
- `get_case` - Requires: code, id
- `update_case` - Requires: code, id
- `list_cases` - Requires: code
- `create_suite` - Requires: code, title
- `create_plan` - Requires: code, title

Runs and results (Executor):
- `create_run` - Requires: code, title
- `create_result` - Requires: code, id, status
- `complete_run` - Requires: code, id
- `list_results` - Requires: code, id

Defects (Healer):
- `create_defect` - Requires: code, title
- `update_defect_status` - Requires: code, id, status

### Workspace files (Chainlit)
Automation and Healer agents **write and edit** Playwright sources under the repo (e.g. `tests/**/*.spec.ts`, `tests/pages/**/*.ts`) using the assistant’s file tools.

### user-github (version control + PRs)
**Automation:** Create branch, commit test files, push, open pull request (tool names depend on server — read `mcps/user-github/tools/*.json` first). Use real `owner`/`repo` from `GITHUB_REPOSITORY` or the GitHub URL.

**Healer:** Push follow-up commits to the **same** branch Automation used so the open PR updates; prefer the same MCP or terminal `git` with `GITHUB_TOKEN` / `GH_PAT`.

**Executor:** Usually uses **git** in the workspace to `checkout` / `pull` Automation’s `branch` before `npx playwright test`.

### user-microsoft/playwright-mcp (Browser)
Automation (DOM inspection), Executor (step execution), Healer (re-identification). **Headed vs headless:** controlled by the MCP server process (`--headless` / env **`PLAYWRIGHT_MCP_HEADLESS`**). For a visible window, do not force headless in Chainlit/Cursor MCP settings.

- `browser_navigate` - Requires: url
- `browser_click` - Requires: element (description), ref (snapshot ref)
- `browser_type` - Requires: element, ref, text
- `browser_fill_form` - Requires: values
- `browser_snapshot` - DOM state capture
- `browser_take_screenshot` - Visual screenshot
- `browser_wait_for` - Wait for conditions
- `browser_console_messages` - Console log capture
- `browser_network_requests` - Network traffic capture

## Always Check Schema First
Before calling any MCP tool, read its schema file at:
`mcps/{server}/tools/{tool-name}.json`
