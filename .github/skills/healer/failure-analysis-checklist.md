# Failure Analysis Checklist

## Step 1 - Classify Failures

- [ ] Read Executor Agent output and extracted `failures` array
- [ ] For each failure, analyzed error message and stack trace
- [ ] Classified each failure into one category:
  - [ ] **Script Issue**: Element not found, selector changed, assertion mismatch
  - [ ] **Data Issue**: Missing data, invalid credentials, stale entities
  - [ ] **Functional Defect**: Unexpected behavior, wrong response, 500 errors
  - [ ] **Environment Issue**: Timeout, network error, service unavailable
- [ ] Documented classification reasoning for each failure

## Step 2 - Self-Healing (Script Issues)

### Chainlit — Selector/Locator healing
- [ ] Opened failing spec under `tests/` (and page object if stack references it)
- [ ] Used `browser_navigate` / `browser_snapshot` on the failure screen
- [ ] Fixed invalid patterns using real locators from the DOM (no invented IDs without proof)
- [ ] Saved edits to workspace files
- [ ] Committed and **pushed** changes to the same Automation/Executor **branch** (PR updates)
- [ ] Re-ran the affected test flow (`npx playwright test` and/or MCP) to verify
- [ ] If still failing after a real fix attempt: `createJiraIssue` + `create_defect`

### Timing healing
- [ ] Identified timing-sensitive step
- [ ] Added `browser_wait_for` (and/or updated Playwright source) before the failing interaction
- [ ] Re-ran test to verify fix
- [ ] Confirmed test passes with wait added

## Step 3 - Data-Related Failures

- [ ] Documented missing/invalid data details
- [ ] Recorded affected test case ID and step number
- [ ] Set action to `DATA_CORRECTION_NEEDED`
- [ ] Clearly stated execution is paused for this test
- [ ] Did NOT attempt to retry without data correction

## Step 4 - Create Jira Defects (Functional)

- [ ] Created Jira Bug using `createJiraIssue` with:
  - [ ] Project key and issue type "Bug"
  - [ ] Clear summary prefixed with `[Auto-Defect]`
  - [ ] Description with Steps to Reproduce
  - [ ] Expected vs Actual results
  - [ ] Error logs and screenshots referenced
  - [ ] Build version and Test Case ID
- [ ] Created Qase defect using `create_defect` for traceability
- [ ] Linked Jira issue key to Qase defect
- [ ] Added additional context via `addCommentToJiraIssue` if needed

## Step 5 - Update Results & Summary

- [ ] Updated self-healed test results to `passed` via `update_result`
- [ ] All defect links established (Jira ↔ Qase)
- [ ] Generated summary with counts:
  - [ ] Self-healed count
  - [ ] Defects created count
  - [ ] Data corrections needed count
- [ ] Generated output JSON with all actions and details
