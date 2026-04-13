# Qase Designer Skill

## Purpose

Generate comprehensive test cases from planner output, store them in Qase, create test plans, and assess automation feasibility for each test case.

## Identifiers: Jira vs Qase (do not mix tools)

| Pattern | System | MCP tool |
|---------|--------|----------|
| `GPS-7525`, `PROJ-123` | Jira issue key | `getJiraIssue` (Atlassian) |
| `TC-363`, “case **363**”, Qase case id **363** | Qase test case | **`get_case`** (`user-qase`) — **never** `getJiraIssue` |

If the user or transcript references **`TC-<number>`**, treat it as a **Qase** case public id / label, not a Jira project key.

## Qase `create_case` — enum fields and validation errors

**Important:** The Qase MCP tool schema often types `priority`, `type`, `behavior`, `automation` as *strings* with English examples. Many real Qase projects still validate those fields as **numeric IDs** (or custom sets). Models tend to copy the schema examples and send `"medium"`, `"functional"`, `"validation"`, `"automated"` — which triggers **`Validation error: The selected field value is invalid`**. **Ignore string examples for those fields when your workspace is strict.**

### Default payload rule (use this unless you already proved strings work)

On **every first `create_case`** for a batch (and after any validation error):

1. Send only: **`code`**, **`title`**, **`suite_id`**, **`description`** / **`preconditions`** (if needed), **`steps`**.
2. **Do not** send `priority`, `type`, `behavior`, `automation`, `severity`, `layer`, or `status` until a case creates successfully.
3. After one success, add enum fields **one at a time** using **integers** copied from an existing case in the same project (**`get_case`** / **`list_cases`** on a template case), or from **`list_system_fields`** / project settings — **never** guess labels like `"validation"` or `"automated"`.

### Never mix Jira into Qase JSON

- **Do not** include **`cloudId`**, **`issueIdOrKey`**, or any **Atlassian/Jira-only** field on **`create_case`** (or other Qase tools). `cloudId` is for Jira MCP tools only. Extra unknown fields can contribute to validation failures depending on the bridge.

If the API returns **`Validation error: The selected field value is invalid`** (sometimes with “and N more errors”):

1. **Prefer integer enums** for fields that the Qase API documents as coded values, especially:
   - **`automation`**: `1` / `0` (or your project’s ids — confirm with an existing case).
   - **`priority`**, **`type`**, **`behavior`**: often **numeric** in the API even when the UI shows labels (“Medium”, “Functional”, “Positive”). **String** values like `"medium"`, `"functional"`, `"positive"`, `"to-be-automated"` are often rejected.
2. **Retry minimal payload** (step 1 above). Omit optional enum fields until a minimal create succeeds; then add fields one group at a time.
3. **Do not invent enum strings** from generic QA vocabulary — use **`get_case`** / **`list_cases`** on real cases in **this** project, or **`list_system_fields`**, not the MCP schema’s English examples.

## MCP Tools Required

| Tool | Server | Usage |
|------|--------|-------|
| `getJiraIssue` | `user-atlassian` | Fetch Jira story details when planner output is incomplete |
| `get_case` | `user-qase` | Read a test case by id (use for Qase ids / `TC-*` references — not Jira) |
| `list_authors` | `user-qase` | Resolve member identity for case assignment |
| `get_author` | `user-qase` | Verify specific member details |
| `create_suite` | `user-qase` | Create test suite for feature |
| `create_case` | `user-qase` | Create individual test cases |
| `create_plan` | `user-qase` | Create test plan with case IDs |
| `update_case` | `user-qase` | Set automation feasibility status |
| `list_cases` | `user-qase` | Verify created cases |

## Steps

### Step 0a: Verify Story Context

Before creating test artifacts, verify the planner output contains story details:

1. Check the planner input for `summary` and `acceptance_criteria`.
2. Call `getJiraIssue` (`user-atlassian`) with the `jira_key` when you need full issue text, comments, attachments, links, or richer HTML — e.g. if the planner JSON is thin or may omit discussion on the ticket.
3. Parse `fields.summary`, `fields.description` / `renderedFields`, comments, and links. Extract acceptance criteria from the description and from comments when they clarify requirements.
4. Use these real story details for all subsequent test case design. **Never create generic or placeholder test cases.**

### Step 0b: Resolve Member Identity

Before creating any test artifacts, resolve the assignee's Qase member identity:

1. Call `list_authors` (no arguments) to retrieve workspace members.
2. Identify the target assignee by matching `email` or `name`.
3. Record their `entity_id` (this is the `member_id` used across Qase).
4. Qase auto-assigns `member_id` on created cases based on the API token owner.
5. Verify the token owner matches the intended assignee via `get_author` with the resolved `author_id`.

> **Note**: The Qase MCP `create_case` tool does not expose a `member_id` parameter. Cases are auto-assigned to the API token owner. Ensure the Qase API token belongs to the user who should own the test cases.

### Step 1: Create Test Suite

Use `create_suite` with:
- `code`: Project code (e.g., "PROJ")
- `title`: `{FeatureName}_Test_Suite`
- `description`: Feature summary from planner output, plus **where tests run**: application URL, environment name (e.g. QA3), and that credentials for execution are documented in each case’s preconditions

### Step 2: Design Test Cases

**Environment block in every `preconditions` (mandatory)**  
Manual and automated runs must see the same context. Start each test case’s `preconditions` field with a short block like:

```
Environment:
- Application URL: <base URL for the app under test>
- Test username: <email or service account>
- Test password: <value from planner environment_details, pipeline secrets, or team standard>
- Browser: Chromium (or as required)
```

Use the Planner output `environment_details` (`base_url`, `credentials.email`, `credentials.password`) when present. When the orchestrator resolved URL or login in Chainlit, **copy those values into Qase** so each case is self-contained.

**Minimum richness**  
- **description**: 2–5 sentences linking the case to the Jira story and acceptance criteria (not empty, not “TBD”).  
- **steps**: At least **3** steps for typical functional flows (navigate → act → assert). The Qase MCP schema requires **`action`** on **each** step object (there is no separate top-level “step” text field — only objects in the `steps` array). Include **`expected_result`** on **every** step for designer traceability (optional in raw API but mandatory in this workflow). Add **`data`** when useful.  
- **preconditions**: Besides the environment block, add data/state setup (e.g. “User is logged in”, “Cart has line items”) as needed.

For each requirement/acceptance criterion, generate test cases across these categories:

**Positive Scenarios**
- Happy path with valid inputs
- Successful completion flows
- Expected state transitions

**Negative Scenarios**
- Invalid input handling
- Unauthorized access attempts
- Missing required fields

**Edge Cases**
- Boundary values (min, max, empty, null)
- Special characters and encoding
- Concurrent operations
- Large data sets

**Integration Cases**
- Cross-feature interactions
- API contract validation
- Data flow between components

Use `create_case` for each. Populate **`description`**, **`preconditions`** (with environment block), and **`steps`** (`action` / `expected_result`) for traceability.

**Enum fields (`priority`, `type`, `behavior`, `automation`, …):** Follow the **Default payload rule** in the section above — start **without** those keys; add only **integer** ids taken from **`get_case`** / **`list_cases`** (same project) after you have a working baseline. Do **not** send English strings such as `"medium"`, `"validation"`, or `"automated"` unless you have confirmed the project accepts them.

### Step 3: Create Test Plan

Use `create_plan` with:
- `code`: Project code
- `title`: `{FeatureName}_QA_Automation`
- `description`: Include scope, environment, risk assessment, entry/exit criteria
- `cases`: Array of all created case IDs

### Step 4: Automation Feasibility

For each test case, evaluate:

| Criterion | Weight |
|-----------|--------|
| Stable UI/API? | Required |
| No manual validation needed? | Required |
| Deterministic outcome? | Required |
| Data manageable programmatically? | Required |

All criteria must be met for feasibility score = 1.

Use `update_case` to set automation flags using the **same type your API expects** (often **integer** `1` / `0`, not strings like `"to-be-automated"`):
- Feasible → `automation: 1`
- Not feasible → `automation: 0`

### Step 5: Decision Gate 2

- Any TC with feasibility ≥ 1 → `PROCEED`
- No TC feasible → `STOP`

### Step 6: Synthesize Output Arrays (CRITICAL — Do NOT Skip)

Before returning your final JSON, MUST create these arrays from your tool calls:

1. **`automatable_case_ids`**: Extract all case IDs where you called `update_case(..., automation: 1)`. If you created cases with IDs [78, 79, 80, 81] and marked [78, 79, 81] as automatable, then `automatable_case_ids: [78, 79, 81]`.
2. **`manual_case_ids`**: Extract all case IDs where you called `update_case(..., automation: 0)`. For the example above, `manual_case_ids: [80]`.
3. **`test_cases`**: Include all test cases with `id`, `title`, `type`, `behavior`, `feasibility_score`, `automation_status`.

**CRITICAL**: These arrays are NOT optional. The downstream Automation agent depends on `automatable_case_ids` to generate correct test scripts. If these arrays are missing or empty when non-empty ones should exist, the entire pipeline will fail.

## Output Format

Your final JSON output MUST include these fields (also in `.github/agents/qase-designer.agent.md`):

```json
{
  "agent": "qase-designer",
  "status": "PROCEED | STOP",
  "project_code": "GPS",
  "suite_id": 123,
  "plan_id": 456,
  "member": {
    "member_id": 20,
    "name": "Member Name",
    "email": "email@example.com"
  },
  "test_cases": [
    {
      "id": 56,
      "title": "Test Case Title",
      "type": 1,
      "behavior": 1,
      "feasibility_score": 1,
      "automation_status": "automatable"
    }
  ],
  "automatable_case_ids": [56, 57, 59, 60],
  "manual_case_ids": [58]
}
```

**CRITICAL**: 
- `automatable_case_ids` MUST list all case IDs where you called `update_case(..., automation: 1)`. This field is required for downstream agents (automation) to work.
- `manual_case_ids` lists case IDs where you called `update_case(..., automation: 0)`.
- If status is STOP, still include the test_cases and case ID arrays for reference.
- In `test_cases`, use **integer** `type` / `behavior` when that matches what Qase accepted on `create_case`; automation gating only requires correct **`id`** values in `automatable_case_ids`.

## Checklist References

- Test design: `.github/skills/qase-designer/test-design-checklist.md`
- Feasibility: `.github/skills/qase-designer/feasibility-checklist.md`
