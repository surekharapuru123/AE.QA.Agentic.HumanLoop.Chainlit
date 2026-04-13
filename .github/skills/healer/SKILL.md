# Healer Skill

## Purpose

Analyze and classify test failures, perform self-healing for script and timing issues, **push healed Playwright sources to the same Git feature branch / PR** Automation opened, handle data-related pauses, and create Jira defects for functional bugs.

## Chainlit — MCP and workspace

| Tool | Server | Usage |
|------|--------|-------|
| `browser_navigate` | `user-microsoft/playwright-mcp` | Navigate to failed page |
| `browser_snapshot` | `user-microsoft/playwright-mcp` | Re-capture DOM for healing |
| `browser_take_screenshot` | `user-microsoft/playwright-mcp` | Evidence for defects |
| `browser_wait_for` | `user-microsoft/playwright-mcp` | Fix timing issues |
| `createJiraIssue` | `user-atlassian` | Create bug tickets |
| `addCommentToJiraIssue` | `user-atlassian` | Add failure context |
| `create_defect` | `user-qase` | Track defect in Qase |
| `update_defect_status` | `user-qase` | Update defect status |
| `update_result` | `user-qase` | Update healed test results |
| GitHub MCP / git | `user-github` + terminal | **Commit and push** patches to Automation’s `branch`; open PR is updated automatically when commits land on that branch |
| Read / edit files | workspace | Load and patch `tests/**/*.spec.ts` and page objects |

Self-heal means **read failing files → patch selectors or waits → commit + push to the automation branch → re-run** (`npx playwright test` and/or Playwright MCP) to confirm. Simply repeating the same steps without a code change is not a fix.

## Steps

### Step 1: Classify Failure

Analyze each failure from the Executor output:

| Category | Detection Signals |
|----------|------------------|
| **Script Issue** | `ElementNotFound`, selector mismatch, stale element reference, assertion on wrong element |
| **Data Issue** | Authentication failure with test creds, "not found" for test entities, constraint violations |
| **Functional Defect** | HTTP 500, unexpected response body, missing UI element that should exist, wrong business logic |
| **Environment Issue** | Timeout, DNS resolution failure, connection refused, service unavailable (503) |

### Step 2: Self-Healing (Script Issues)

**For Selector/Locator Issues:**
1. `browser_navigate` to the page where failure occurred
2. `browser_snapshot` to capture current DOM
3. Analyze DOM to find the correct selector for the target element
4. Prefer resilient selectors in this order:
   - `[data-testid="..."]`
   - `[aria-label="..."]`
   - `role` selectors
   - CSS class selectors (last resort)
5. Update the page object or test file in the workspace with the new selector
6. **Git:** Check out the same `branch` Executor used (from Automation/Executor JSON), `git add` changed files, `git commit`, `git push` (or equivalent GitHub MCP file/commit APIs per live schema)
7. Re-execute the failed test (`npx playwright test <spec>` preferred) to verify

**For Timing Issues:**
1. Identify the step that failed due to element not yet visible/interactive
2. Add `browser_wait_for` before the failing interaction
3. Re-execute to verify

### Step 3: Data-Related Failures

Do NOT retry. Instead:
1. Document exactly what data is missing/invalid
2. Include the test case ID, step number, and expected data
3. Set action to `DATA_CORRECTION_NEEDED`
4. Await user intervention before re-running

### Step 4: Functional Defects → Jira

Use `createJiraIssue` with:
```json
{
  "cloudId": "<your-cloud-id>",
  "projectKey": "PROJ",
  "issueTypeName": "Bug",
  "summary": "[Auto-Defect] {brief description}",
  "description": "## Steps to Reproduce\n{steps}\n\n## Expected Result\n{expected}\n\n## Actual Result\n{actual}\n\n## Evidence\n- Error: {error_message}\n- Test Case: QA-{case_id}\n- Build: {version}\n- Screenshot: attached"
}
```

Also use `create_defect` in Qase to maintain traceability when the MCP accepts the payload.

**If `create_defect` returns `Invalid request: Data is invalid`:** The workspace may require different required fields, severity codes (integer vs string), or permissions. Retry with **minimal** fields per the live MCP tool schema; if it still fails, create the defect in **Jira** (or Qase UI) manually and reference the **Qase run id** + **case id** in the description — do not block the pipeline on MCP defect creation alone.

### Step 5: Update Results

- Self-healed tests: `update_result` to `passed` after verified re-run
- Defects: Link Jira key to Qase defect
- Output JSON: include `git_branch`, `pr_url` (if known), and `pushed_healing_commits` (boolean) so the orchestrator knows the PR reflects fixes

## Checklist Reference

Always read and follow: `.github/skills/healer/failure-analysis-checklist.md`
