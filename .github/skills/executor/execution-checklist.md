# Execution Checklist

## Step 0 - Checkout Automation branch

- [ ] Read Automation JSON for `branch` (and `pr_url` if present)
- [ ] Ran `git fetch` / `git checkout <branch>` / `git pull` at repo root (or equivalent)
- [ ] Confirmed `scripts[].file_path` exist on disk after checkout

## Step 1 - Resolve Member & Create Test Run

### Member Resolution
- [ ] Called `list_authors` to retrieve workspace members
- [ ] Identified executing user by `email` or `name`
- [ ] Recorded `entity_id` as the `member_id` for this execution

### Create Test Run
- [ ] Read Automation Agent output for `project_code`, case IDs, script mapping
- [ ] Created test run using `create_run` with:
  - [ ] Title: Automatable_Test-Generation_Run_{timestamp}
  - [ ] Description includes executor identity: `Executed by: {name} (member_id: {id})`
  - [ ] `is_autotest: true`
  - [ ] ONLY automatable_case_ids in `cases` array (no include_all_cases — avoids irrelevant cases from other versions)
- [ ] Recorded **`run_id` from the MCP/tool response body** (numeric) — not invented (`AUTO_GENERATED_ID`, etc.)
- [ ] Final executor JSON and user-facing summary use that same real **`run_id`**

## Step 2 - Execute Tests

### Playwright CLI (recommended when branch is checked out)

- [ ] Ran `npx playwright test` (or `npm run test`) for paths in Automation `scripts[]` where appropriate

### Chainlit (Playwright MCP)
- [ ] Used `browser_navigate` to open the target URL for each test
- [ ] Executed each test step using:
  - [ ] `browser_click` for interactions
  - [ ] `browser_type` / `browser_fill_form` for text input
  - [ ] `browser_select_option` for dropdowns
  - [ ] `browser_wait_for` for dynamic content
- [ ] Used `browser_snapshot` to capture DOM for assertions
- [ ] Used `browser_take_screenshot` at every step (naming: `TC{case_id}_step{N}.png`)
- [ ] Uploaded each screenshot to Qase via REST API and recorded hashes
- [ ] On failure: captured `browser_console_messages` and `browser_network_requests`
- [ ] Recorded status, execution time, errors per test case

## Step 3 - Report Per-Case Results with Screenshots (CRITICAL)

### Qase REST API (step-level)
- [ ] Called `get_case` for each test case to retrieve step definitions
- [ ] For each step: recorded `action`, `expected_result`, `position` from case
- [ ] Built result JSON with full step data including:
  - [ ] `action` and `expected_result` copied from case steps
  - [ ] `comment` as actual result
  - [ ] `attachments` with screenshot hashes per step
- [ ] Submitted via REST API (NOT MCP `create_result`) to preserve step names
- [ ] Verified response `"status": true`

## Step 4 - Complete & Summarize

- [ ] Called `complete_run` to finalize the test run
- [ ] Calculated pass rate: (passed / total) * 100
- [ ] Identified all failures with details
- [ ] Generated output JSON with complete summary, results_reported, and failures
- [ ] Included **`artifact_paths.scripts`** (and pages) listing every repo-relative path from Automation `scripts[]` / page objects
- [ ] Did **not** claim step screenshots or Qase attachments unless upload + result POST succeeded
