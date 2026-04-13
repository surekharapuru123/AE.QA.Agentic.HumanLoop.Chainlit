# Executor Skill

## Purpose

Create test runs in Qase, execute Playwright tests **from the Automation feature branch** when provided, report per-case results with screenshots back to Qase, and complete the run.

## Chainlit — Tools

| Tool | Server | Usage |
|------|--------|-------|
| `list_authors` | `user-qase` | Resolve member identity |
| `get_author` | `user-qase` | Verify member details |
| `create_run` | `user-qase` | Create test run |
| `complete_run` | `user-qase` | Finalize test run |
| `get_case` | `user-qase` | Get case steps for result reporting |
| `list_results` | `user-qase` | Verify results are recorded |
| `create_environment` | `user-qase` | Create QA environment |
| `browser_navigate` | `user-microsoft/playwright-mcp` | Navigate to URLs |
| `browser_click` | `user-microsoft/playwright-mcp` | Click elements |
| `browser_type` | `user-microsoft/playwright-mcp` | Type text |
| `browser_fill_form` | `user-microsoft/playwright-mcp` | Fill forms |
| `browser_select_option` | `user-microsoft/playwright-mcp` | Select dropdowns |
| `browser_snapshot` | `user-microsoft/playwright-mcp` | Capture DOM state |
| `browser_take_screenshot` | `user-microsoft/playwright-mcp` | Visual screenshots |
| `browser_wait_for` | `user-microsoft/playwright-mcp` | Wait for elements |
| `browser_console_messages` | `user-microsoft/playwright-mcp` | Capture console logs |
| `browser_network_requests` | `user-microsoft/playwright-mcp` | Capture network traffic |

**Visible browser:** Playwright MCP launches Chromium (or another channel) in a **window** unless the MCP server was started with **`--headless`** or **`PLAYWRIGHT_MCP_HEADLESS=1`**. If the user sees no window but sees `browser_*` tool steps in Chainlit, switch the Playwright MCP server to headed (env `PLAYWRIGHT_MCP_HEADLESS=false`, remove `--headless` from args). If there are **no** `browser_*` tool steps, the model did not execute via MCP — fix prompts / stage instructions, not headless mode.

> **Step-level results in Qase:** Use the Qase REST API directly (e.g. `curl`), because the Qase MCP `create_result` tool's `steps` schema lacks `action` and `expected_result` fields, causing empty step names in Qase UI. Use `get_case` first to retrieve step definitions.

**Git branch:** Read Automation JSON for `branch`. Before relying on files, run `git fetch` and `git checkout <branch>` && `git pull` at the repo root (terminal or equivalent) so Executor executes the same commit the PR shows. If Automation did not push, use the current workspace and say so in the executor summary.

## Steps

### Step 0: Checkout Automation branch

1. From Automation output, read `branch` (and optional `pr_url`).
2. In the repository root: `git fetch origin`, `git checkout <branch>`, `git pull` (or `git merge` as appropriate for your flow).
3. Confirm `scripts[].file_path` from Automation exist on disk; if not, stop and report **blocked** with a clear message.

### Step 1: Resolve Member & Create Test Run

**1a. Member Resolution**

1. Call `list_authors` (no arguments) to retrieve workspace members.
2. Identify the executing user by matching `email` or `name`.
3. Record their `entity_id` (this is the `member_id` used across Qase).

**1b. Create Test Run**

Call `create_run` with:
- `code`: project code
- `title`: `Automatable_Test-Generation_Run_{timestamp}` (e.g. Automatable_Test-Generation_Run_20260317_163000) — clearly identifies runs from the pipeline's automatable test-generation flow
- `description`: `Executed by: {member_name} (member_id: {member_id})`
- `is_autotest`: `true`
- `cases`: ONLY automatable_case_ids from automation input — do NOT use include_all_cases or plan_id to pull in extra cases (adds irrelevant tests from other versions)
- `environment_id`: QA environment ID (create with `create_environment` if needed)

Save the `run_id` from the response for all subsequent steps.

**Forbidden:** Never invent or summarize with a fake id (`AUTO_GENERATED_ID`, `TBD`, string placeholders). If `create_run` was not called or failed, say so and set executor `status` accordingly — do not fabricate pass/fail stats.

### Step 2: Execute Tests (Playwright MCP and/or CLI)

**Recommended:** Run **`npx playwright test`** (or `npm run test`) targeting the spec paths from Automation `scripts[]` on the checked-out branch — matches CI and validates the PR’s code.

**Alternatively / additionally:** For each test case, drive the app with Playwright MCP tools:

1. **Navigate**: `browser_navigate` to the target URL
2. **Interact**: Use `browser_click`, `browser_type`, `browser_fill_form`, `browser_select_option`
3. **Wait**: Use `browser_wait_for` when elements need time to load
4. **Verify**: Use `browser_snapshot` to check DOM state against expected results
5. **Screenshot (pass and fail)**: Capture evidence for **every** case — not only failures. Use `browser_take_screenshot` after key assertions (or `test.afterEach` in Playwright: `page.screenshot({ path: \`screenshots/case_${caseId}_${testInfo.status}.png\`, fullPage: true })`). Name files with the **numeric Qase `case_id`** (e.g. `case_363_passed.png`), not a fake Jira-style `TC-363` key.
6. **Upload**: Upload each screenshot to Qase via REST API (`POST /v1/attachment/{PROJECT_CODE}` or your org’s attachment endpoint), then reference returned attachment hash(es) on **step** or **result** payloads per [Qase API docs](https://developers.qase.io).
7. **Debug**: On failure, use `browser_console_messages` and `browser_network_requests`

Record per test case:
- Start time, end time, duration (ms)
- Pass/fail status
- Screenshot hashes per step
- Error messages and stack traces (on failure)

### Step 3: Report Per-Case Results with Screenshots

**You MUST report a result for EVERY case in the run** only after that case was **actually executed** (Playwright or agreed manual protocol). Do **not** bulk-submit `passed` / `failed` to Qase from guessed outcomes — if tests were not run, status must be **`blocked`** or **`skipped`** with an honest comment.

**Screenshots:** Attach (or reference) at least one screenshot per case for **both** passes and fails when upload is available, so Qase shows visual evidence for the whole run.

#### Qase REST API (step-level)

> Use the Qase REST API directly for step-level results. The MCP tool's `steps` schema lacks `action`/`expected_result`, causing empty step names in the Qase UI.

For each test case:
1. Call `get_case` to retrieve step definitions (`action`, `expected_result`, `position`).
2. Build the result JSON:
   - `case_id`, `status`, `time_ms`
   - `comment`: `Executed by: {member_name} (member_id: {member_id})` + notes
   - `stacktrace`: for failures
   - `steps`: each with `position`, `status`, `action` (from case), `expected_result` (from case), `comment` (actual result), `attachments` (screenshot hashes)
3. Submit via REST API:
   ```
   curl -s -X POST "https://api.qase.io/v1/result/{PROJECT_CODE}/{run_id}" \
     -H "Token: {QASE_API_TOKEN}" \
     -H "Content-Type: application/json" \
     -d @payload.json
   ```

If you cannot map execution evidence to a case, report status `blocked` with a clear comment.

**MCP `create_results_bulk` / `create_result`:** If the tool schema supports **`attachments`** (or equivalent) on each result, include uploaded screenshot IDs so the Qase run shows images for **passed** and **failed** cases. If attachments are not exposed, use the **REST** flow above for step-level results with screenshots — do not claim screenshots were attached unless upload succeeded.

### Step 4: Complete Run

1. Call `complete_run` with the `run_id` to finalize.
2. Use `list_results` to verify all results are recorded.
3. Calculate pass rate and build the output summary.

### Output: script paths and branch for the user

Echo every **`scripts[].file_path`** (and **`page_objects`** if present) from the Automation stage into your summary JSON, e.g. `artifact_paths.scripts` and `artifact_paths.pages`, using **paths relative to the repository root** (the same strings Automation used). Set **`git_branch`** to the branch you executed (copy Automation `branch` after checkout). Optionally add `artifact_paths.note`: full absolute paths are `{repository_root}/{relative}` where `repository_root` is the folder containing `app.py` / `tests/`.

## Checklist Reference

Always read and follow: `.github/skills/executor/execution-checklist.md`
