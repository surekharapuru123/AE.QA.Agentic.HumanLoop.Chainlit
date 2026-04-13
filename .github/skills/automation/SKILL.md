# Automation Skill

## Purpose

Inspect the real application DOM **using Playwright MCP first**, generate Playwright TypeScript from **selectors observed in live snapshots**, link scripts back to test cases in Qase, **write files into this repository**, then **push to GitHub on a feature branch and open (or update) a PR** so Stage 4 runs from that branch and Stage 5 can push fixes to the same PR.

## Chainlit — Tools

| Tool | Server | Usage |
|------|--------|-------|
| `browser_navigate` | `user-microsoft/playwright-mcp` | Navigate to target page |
| `browser_snapshot` | `user-microsoft/playwright-mcp` | Capture DOM for selector extraction |
| `browser_click` | `user-microsoft/playwright-mcp` | Interact to reveal multi-step flows |
| `browser_hover` | `user-microsoft/playwright-mcp` | Open flyout / nested menus before clicking |
| `browser_fill` | `user-microsoft/playwright-mcp` | Fill fields (use env-backed secrets when available) |
| `browser_wait_for` | `user-microsoft/playwright-mcp` | Wait for selectors or time |
| `get_case` | `user-qase` | Fetch full test case details |
| `list_cases` | `user-qase` | List cases by suite/project |
| `update_case` | `user-qase` | Update automation status |
| GitHub MCP ops | `user-github` (or org server id) | Create branch, commit files, `push`, open/update PR (`create_pull_request`, file APIs per live schema) |
| Workspace writes | assistant file tools | Create/update specs under `tests/` and POMs under `tests/pages/` |

**Navigation:** Prefer **menu → submenu → page** during MCP exploration. `browser_snapshot` may return `navigation_hints` with **`links[].keywords`**, **`path_segments`**, and **`selection_policy.rules`** (stable ids) — rank routes by **overlap** between those keywords and the Qase case (title/steps), then use the link’s `preferred_selector` or `pathname`. For **generated Playwright**, prefer **`page.goto(<pathname>)`** when `pathname` is from that chosen link or the snapshot URL. MCP can click **hidden** flyout links, but **`page.click('a[href="…"]')` in tests often times out** waiting for visibility. Do not invent paths; use only observed `pathname` values.

## Steps

### Step 1: Fetch Automatable Test Cases

From Qase Designer output, get `automatable_case_ids` and `project_code`.

For each ID, use `get_case` to retrieve:
- Title, description, preconditions
- Steps with actions and expected results
- Priority, type, behavior
- Tags

### Step 2: Inspect the Real Page DOM (CRITICAL)

**Before writing ANY code**, you MUST inspect the actual target application to get real selectors.

#### Chainlit (Playwright MCP)

1. `browser_navigate` to the application base URL
2. Observe if the page redirects (e.g., to Okta SSO)
3. `browser_snapshot` to capture the current DOM
4. Extract all interactive elements and their attributes:
   - `data-testid`, `aria-label`, `id`, `name`, `placeholder`, `type`
5. For multi-step flows (login → password page), interact and snapshot each page
6. For SSO / deep menus: after each screen change, snapshot again; use `browser_hover` / `browser_click` so targets are visible before asserting locators
7. Record the selectors you'll use in the page objects

**You MUST use real selectors. Do NOT invent or guess selectors.**

#### Multi-step features: search/list vs action surface — non-negotiable

Many apps split **search or list** steps from the screen where **row/cart/grid** actions run. Qase titles often describe the latter; your snapshots must reflect the **same surface** the user would use for those actions.

1. After login, navigate toward the feature using only links and controls from `browser_snapshot` / `navigation_hints` (menu → submenu → page as needed).
2. If the first screen is **only** search/filter/list, call `browser_snapshot`, find the control that continues to the **list/cart/grid** where the case applies (from `elements[]`), click it, wait for navigation, then `browser_snapshot` again.
3. **Do not write final specs until** the latest snapshot’s URL or title matches the screen where the case’s controls actually live (row actions, checkboxes, duplicate, dialogs). Stopping on an intermediate search-only view means you do not yet have selectors for grid/cart actions.
4. Every locator for those tests must appear in `elements[]` from a snapshot **on that target screen** (or use `test.skip` with a reason).

Skipping ahead without a snapshot on the action surface is the main cause of wrong navigation and invented `#id` selectors.

### Step 3: Generate Playwright Scripts

**Pipeline contract — `scripts[]` vs Qase cases:**

- For **each** ID in `automatable_case_ids`, emit **one** `scripts[]` object with that `case_id` and a unique `file_path` (one spec file per case is typical).
- `scripts.length` must equal `automatable_case_ids.length`. A single `login.spec.ts` must **not** stand in for multiple unrelated feature cases.
- **POM:** `tests/pages/{name}.page.ts`. **Specs:** `tests/{feature}/{name}.spec.ts` (import from `../pages/...` as needed). Avoid `tests/{feature}/pages/`.

**Playwright vs MCP exploration:** Tools may use force/DOM behavior on hidden nav links. Generated **`page.click`** does not — use **`page.goto(pathname)`** from `navigation_hints` for post-login navigation when possible, or a full visible parent→child chain. Okta password: **`[name="credentials.passcode"]`** only, never `#credentials…` escaped forms.

**DOM inspection vs placeholders (non-negotiable):**

- Selectors must come from **browser snapshot / navigation hints** — not generic guesses. Prefer a second inspection pass for **authenticated or feature URLs** when the case requires them.
- **`test.step` callbacks must include real `await` Playwright usage.** Do not ship steps that only contain `// comment` lines. Either implement with real locators or `test.skip('…')`.
- **Per-step evidence (Qase):** At the end of **each** `test.step`, call `attachStepEvidence(testInfo, page, '01-login')` from `tests/utils/test-helpers.ts` (or equivalent `testInfo.attach` with `page.screenshot`). End-of-test `test-finished-1.png` alone cannot prove each step’s screen; without per-step attaches, Qase steps and screenshots will look mismatched.
- **No invented action IDs:** Do not emit `#duplicateBtn`, `#addCart`, etc. unless that exact `id` appears in a **snapshot on the cart/action surface**. Prefer `getByRole('button', { name: /duplicate/i })`, `[data-testid="…"]`, or a stable selector from `elements[]` after navigating to the real cart/grid.
- Page object files must be **complete and compilable** (full class, all methods the spec calls). Multi-screen login flows need **all** screens represented in the POM.

**Page Object Model Pattern** — using REAL selectors from Step 2:

```typescript
import { type Page, type Locator } from '@playwright/test';

export class LoginPage {
  readonly page: Page;
  readonly usernameInput: Locator;
  readonly passwordInput: Locator;
  readonly signInButton: Locator;

  constructor(page: Page) {
    this.page = page;
    // Selectors from real DOM inspection — NOT guessed
    this.usernameInput = page.locator('[name="identifier"]');
    this.passwordInput = page.locator('[name="credentials.passcode"]');
    this.signInButton = page.locator('[data-type="save"]');
  }

  async goto() {
    await this.page.goto('/');
  }

  async login(email: string, password: string) {
    await this.usernameInput.fill(email);
    await this.signInButton.click();
    await this.passwordInput.waitFor();
    await this.passwordInput.fill(password);
    await this.signInButton.click();
  }
}
```

**Test Spec Pattern:**
```typescript
import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';

test.describe('Login Feature @regression @gps-login', () => {
  test('successful login with valid credentials @smoke @automated', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await test.step('Navigate to login page', async () => {
      await loginPage.goto();
    });
    await test.step('Enter credentials and submit', async () => {
      await loginPage.login('user@test.com', 'password123');
    });
    await test.step('Verify successful redirect', async () => {
      await expect(page).toHaveURL(/dashboard/);
    });
  });
});
```

**Key rules:**
- Navigation method: `goto()` (not `navigate()`)
- All selectors from real DOM inspection
- Every test title includes `@automated` tag
- No hardcoded URLs (use `baseURL` from config)
- No hardcoded credentials (use environment config)
- Use `test.step()` for structured reporting

**CRITICAL — NO PLACEHOLDERS OR STUBS:**
- Every test MUST have fully implemented steps with real Playwright actions and assertions.
- NEVER leave empty test bodies, comments like "Assume we've logged in", "will be scripted here", or TODO placeholders.
- If a test requires multi-step setup (e.g., logout needs login first), implement the full flow: login in `beforeEach` or within the test, then perform the logout steps.
- If a test case cannot be automated with the current DOM, skip it with `test.skip()` and a clear reason — do NOT push a stub.

**Example — Logout (full implementation, no placeholders):**
```typescript
test('Logout Functionality @automated', async ({ page }) => {
  const loginPage = new LoginPage(page);
  const dashboardPage = new DashboardPage(page);

  await test.step('Login first', async () => {
    await loginPage.goto();
    await loginPage.enterUsername('user@test.com');
    await loginPage.enterPassword('validPassword');
    await loginPage.clickSubmit();
    await expect(page).toHaveURL(/dashboard/);
  });

  await test.step('Click logout', async () => {
    await dashboardPage.logoutButton.click();
  });

  await test.step('Verify redirected to login', async () => {
    await expect(page).toHaveURL(/login|signin|\/$/);
    await expect(loginPage.signInHeading).toBeVisible();
  });
});
```

**Example — Security test (full implementation):**
```typescript
test('Injection Attack Prevention @automated', async ({ page }) => {
  const loginPage = new LoginPage(page);

  await test.step('Navigate to login page', async () => {
    await loginPage.goto();
    await expect(loginPage.signInHeading).toBeVisible();
  });

  await test.step('Enter SQL injection payload in username', async () => {
    await loginPage.enterUsername("admin' OR '1'='1");
    await loginPage.clickSubmit();
  });

  await test.step('Verify login is rejected or error shown', async () => {
    await expect(page).not.toHaveURL(/dashboard/);
    await expect(loginPage.errorMessage).toBeVisible();
  });
});
```

### Step 4: Link Scripts to Test Cases

Use `update_case` for each test case:
- Set `automation` to `"automated"`
- Add script path reference

### Step 5: Persist files in the workspace

1. Write every spec and page object to disk under `tests/{feature}/` and `tests/pages/` (respect the layout in this skill).
2. Ensure paths match what you will reference in `update_case` and in the `scripts[]` output.

### Step 6: Push to GitHub (feature branch + PR)

**Goal:** Executor must run tests from the **same branch** that holds the generated code; Healer must be able to **commit fixes to that branch** so the existing PR shows updated commits.

1. **Branch name:** Use a predictable convention, e.g. `qa/e2e-{jira_key}-{feature_slug}` or `feat/{feature_slug}-playwright` (no spaces; align with team policy). Base branch is typically `main` or `develop` — use the repo default from GitHub or `.env` hints (`GITHUB_REPOSITORY`, default branch from `get_repo` if available).
2. **Git / GitHub MCP:** Create the branch from the default branch, add **only** the new/changed files under `tests/`, commit with a clear message (include Jira key + Qase case ids if known), **push** the branch, then **open a pull request** (or add commits to an existing open PR for the same branch).
3. **Credentials:** Use `GITHUB_TOKEN` / `GH_PAT` from `.env` (Chainlit with `CHAINLIT_MCP_FULL_ENV=1` so MCP children inherit vars). Use **real** `owner` / `repo` from the URL or `GITHUB_REPOSITORY` — never placeholder owner/repo names.
4. **Output JSON (required when push succeeds):** Set `branch`, `pr_url`, and `pr_number` on the Automation output per `.github/rules/agent-output.md`. If GitHub is unreachable, still complete local files and set `status` with an honest note — Executor may run against the local workspace only when the branch was not pushed.

## Checklist Reference

Always read and follow: `.github/skills/automation/script-generation-checklist.md`
