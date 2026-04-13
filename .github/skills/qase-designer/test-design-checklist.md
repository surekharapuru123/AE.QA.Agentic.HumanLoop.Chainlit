# Test Design Checklist

## Step 0 - Resolve Member Identity

- [ ] Called `list_authors` to retrieve workspace members
- [ ] Identified target assignee by `email` or `name`
- [ ] Recorded `entity_id` as the `member_id` for case ownership
- [ ] Verified API token owner matches intended assignee via `get_author`
- [ ] If mismatch, logged warning for manual reassignment

## Step 1 - Create Test Suite

- [ ] Read Planner Agent output and confirmed `status: PROCEED`
- [ ] Created test suite using `create_suite` with project code
- [ ] Suite title follows naming convention: `{FeatureName}_Test_Suite`
- [ ] Suite description includes feature summary from planner

## Step 2 - Design & Create Test Cases

### Coverage Verification
- [ ] Generated positive scenarios (happy path flows)
- [ ] Generated negative scenarios (invalid inputs, unauthorized access)
- [ ] Generated edge cases (boundary values, empty states, max limits)
- [ ] Generated integration cases (cross-feature, API contracts)
- [ ] Tagged regression-relevant cases with `regression` tag

### Per Test Case Quality
- [ ] Title is descriptive and unique
- [ ] **Preconditions** include **Application URL**, **test username**, and **test password** (from planner `environment_details` or pipeline/Jira), then any other setup
- [ ] **Description** is substantive (2+ sentences) and references the story / acceptance criteria
- [ ] **Steps** include at least 3 steps for typical functional cases (unless trivial smoke)
- [ ] Steps array has `action` and `expected_result` for each step
- [ ] **`create_case` enums**: First attempt uses **`code`, `title`, `suite_id`, description/preconditions, `steps` only** — **omit** `priority` / `type` / `behavior` / `automation` until one case succeeds; then add **integer** ids from **`get_case`** / **`list_cases`**, not MCP schema string examples (`"medium"`, `"validation"`, …)
- [ ] **No Jira fields on Qase tools**: `create_case` has **no** `cloudId` / `issueIdOrKey` — do not paste Atlassian UUIDs into Qase JSON
- [ ] **Enums for Qase API**: If `create_case` returns **“The selected field value is invalid”**, retry **minimal** payload, then **integer** codes only — not unverified strings like `"medium"` or `"to-be-automated"`
- [ ] Tags applied for categorization (omit if they trigger validation errors)
- [ ] Suite ID links to the created suite

### Storage Verification
- [ ] All test cases created successfully via `create_case`
- [ ] On validation failure: retried **minimal** payload (`code`, `title`, `suite_id`, `steps`), then re-added fields; or switched string enums → **numeric** enums
- [ ] Verified case IDs returned from API
- [ ] No duplicate test cases created
- [ ] Did **not** call `getJiraIssue` for **Qase** references (`TC-*` / numeric Qase case id — use **`get_case`**)

## Step 3 - Create Test Plan

- [ ] Test plan created using `create_plan`
- [ ] Title follows convention: `{FeatureName}_QA_Automation`
- [ ] Description includes:
  - [ ] Scope of testing
  - [ ] Environment: QA
  - [ ] Risk and mitigation strategies
  - [ ] Entry criteria
  - [ ] Exit criteria
- [ ] All created case IDs included in the plan
- [ ] Plan ID recorded for output
