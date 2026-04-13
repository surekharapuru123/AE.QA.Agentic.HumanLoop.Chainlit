# Test Generation Rules

## Playwright MCP before new files (Automation Agent)

- Use **`user-microsoft/playwright-mcp`** tools to **`browser_navigate`** to the app and reach the **real target screen** for the case (login + menus as needed), then **`browser_snapshot`**.
- **Do not** add or change `tests/**/*.spec.ts` or `tests/pages/**/*.page.ts` until that snapshot on the target screen exists; selectors must be taken from MCP output, not invented.

## Page Object Model
- Every page MUST have a corresponding page object class in `tests/pages/`
- Page objects MUST use `Locator` typed properties, not raw selectors
- All user interactions MUST go through page object methods
- Page constructors accept `Page` from Playwright

## Selectors (Priority Order)
1. `[data-testid="..."]` - Preferred for all custom elements
2. `[aria-label="..."]` or `role` selectors - For accessible elements
3. `text=...` - For text-based identification
4. CSS selectors - Last resort only

## Test Structure
- Use `test.describe` blocks grouped by feature
- Use `test.step` for reporting-friendly step grouping
- Use `test.beforeEach` / `test.afterEach` for setup/teardown
- Tag tests with `@smoke`, `@regression`, `@{feature-name}`

## No Placeholders or Stubs
- Every test MUST have fully implemented steps with real Playwright actions and assertions
- NEVER leave empty test bodies, "Assume we've logged in", "will be scripted here", or TODO placeholders
- Multi-step flows (e.g., logout) must include full setup (login first) and real assertions
- If a case cannot be automated, use `test.skip('reason')` — do NOT push a stub

## Assertions
- Use `expect(locator)` over `expect(page)` where possible
- Always include meaningful assertion messages
- Use `toBeVisible()`, `toHaveText()`, `toHaveURL()` over generic `toBeTruthy()`

## No Hardcoding
- URLs: Use `baseURL` from Playwright config
- Credentials: Use environment variables via `tests/config/`
- Test data: Use factories or config files

## File Naming
- Specs: `{feature}.spec.ts` (e.g., `login.spec.ts`)
- Pages: `{page-name}.page.ts` (e.g., `login.page.ts`)
- Utilities: `{purpose}.ts` (e.g., `test-helpers.ts`)
