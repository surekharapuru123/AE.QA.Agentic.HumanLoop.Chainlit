# Script Generation Checklist

## Step 1 - Fetch Automatable TCs

- [ ] Read Qase Designer output and confirmed `status: PROCEED`
- [ ] Extracted `automatable_case_ids` and `project_code`
- [ ] Fetched each case using `get_case`
- [ ] Confirmed each case has `automation: "to-be-automated"`
- [ ] Collected all step details (action, expected_result, data)

## Step 2 - Inspect Real Page DOM

### Chainlit (Playwright MCP)
- [ ] Used `browser_navigate` to open the application base URL
- [ ] Observed and followed any redirects (e.g., Okta SSO)
- [ ] Used `browser_snapshot` to capture the DOM
- [ ] Extracted all interactive elements with attributes (data-testid, aria-label, id, name, placeholder)
- [ ] For multi-step flows, interacted and snapshotted each page
- [ ] For nested / flyout menus: used `browser_hover` / parent click so targets are visible before recording selectors
- [ ] For feature areas beyond the shell, used menu → submenu navigation unless Qase gives a direct URL — no invented `goto('/made-up-path')` in generated code
- [ ] Recorded real selectors for page objects

### Gate — real screen before any script files (CRITICAL)
- [ ] Did **not** create or edit any `tests/**/*.spec.ts` or `tests/pages/**/*.page.ts` until MCP navigation + snapshot were done on the **target** screen
- [ ] Used **`browser_navigate`** and, where needed, **`browser_click` / `browser_hover` / `browser_fill` / `browser_wait_for`** so the browser shows the **same surface** as the Qase steps (not stopped on login/search-only unless the case is limited to that)
- [ ] Called **`browser_snapshot`** **after** arriving on that target screen; final selectors for the case come from that snapshot (or an equivalent screen in the same flow)

### Selector Verification
- [ ] Every selector in page objects comes from real DOM inspection
- [ ] No selectors were guessed or invented
- [ ] Preferred selector priority: `data-testid` > `aria-label` > `id` > `name` > `placeholder`

## Step 3 - Generate Scripts

### Structure
- [ ] Created feature directory under `tests/{feature-name}/`
- [ ] Created page objects in `tests/pages/`

### Page Object Quality
- [ ] Follows Page Object Model pattern
- [ ] Navigation method is `goto()` (NOT `navigate()`)
- [ ] Uses `page.goto('/')` or relative URL internally
- [ ] All selectors from real DOM inspection (Step 2)
- [ ] Selector preference: `data-testid` > `aria-label` > `id` > `name` > `placeholder`

### Test Spec Quality
- [ ] Each test uses `test.describe` with feature name
- [ ] Individual tests use `test()` with descriptive names
- [ ] Every test title includes `@automated` tag
- [ ] Tags applied: `@smoke`, `@regression`, `@{feature-name}`
- [ ] Critical steps wrapped in `test.step()` for reporting
- [ ] Uses `expect` assertions with clear failure messages
- [ ] No hardcoded URLs (uses `baseURL` from config)
- [ ] No hardcoded credentials (uses environment config)
- [ ] Proper `beforeEach` / `afterEach` setup/teardown

### NO Placeholders or Stubs (CRITICAL)
- [ ] Every test has fully implemented steps — no empty bodies
- [ ] No comments like "Assume we've logged in", "will be scripted here", or TODO placeholders
- [ ] **Inside `test.step`, no comment-only bodies** — each step must have at least one `await` (`expect`, click, fill, etc.); not just `// Navigate…` / `// Click…`
- [ ] Page objects are **complete** (full class); multi-step login (email → Next → password) has locators/methods for **each** screen from inspection
- [ ] For cases that need a feature screen beyond login, **inspect** that screen and use a dedicated POM class named after the feature (from `browser_snapshot`), not login-only code
- [ ] Multi-step flows (e.g., logout) include full setup: login first, then perform the test steps
- [ ] If a case cannot be automated, use `test.skip('reason')` — do NOT ship a stub

## Step 4 - Link Scripts to Test Cases

- [ ] Updated each case in Qase via `update_case`
- [ ] Set `automation` field to `"automated"`
- [ ] Recorded script file path for each case

## Step 5 - Write files to workspace

- [ ] Saved all specs under `tests/{feature-name}/` and POMs under `tests/pages/`
- [ ] `scripts[].file_path` in output matches files on disk
- [ ] Output JSON includes `test_dir`, `scripts`, `total_scripts`, `automatable_case_ids`, `project_code`, `plan_id`, `suite_id`

## Step 6 - GitHub branch + PR

- [ ] Created a feature branch (naming per `.github/skills/automation/SKILL.md` Step 6)
- [ ] Committed only the intended `tests/` changes, pushed to `origin`, opened (or updated) a PR
- [ ] Output JSON includes `branch`, `pr_url`, `pr_number` when push succeeded (or honest note if GitHub unavailable)
