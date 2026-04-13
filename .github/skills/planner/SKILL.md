# Planner Skill

## Purpose

Fetch Jira user stories and perform structured gap analysis to determine test readiness before test case generation begins.

## MCP Tools Required

| Tool | Server | Usage |
|------|--------|-------|
| `getJiraIssue` | `user-atlassian` | Fetch issue details by key |
| `searchJiraIssuesUsingJql` | `user-atlassian` | Fetch linked/child issues |
| `addCommentToJiraIssue` | `user-atlassian` | Post gap report as comment |

## Steps

### Step 1: Jira Fetching

Use `getJiraIssue` with the provided `cloudId` and `issueIdOrKey`. Extract:
- `fields.summary` → Title
- `fields.description` → Full description (parse for acceptance criteria)
- `fields.attachment` → Attachments list
- `fields.issuelinks` → Linked issues
- `fields.labels` → Labels
- `fields.components` → Components
- **Rich Jira payload:** When `getJiraIssue` returns extended context (e.g. full comments, remote links), use those for environment hints, clarifications, and dependencies that are not in the description alone.

For linked issues, use `searchJiraIssuesUsingJql` with JQL:
```
issue in linkedIssues("PROJ-123")
```

**Extract environment details** from the issue content:
- Scan the description, acceptance criteria, custom fields, and comments for:
  - **base_url**: URLs matching the application domain (e.g., `https://qa3.gps.aegm.com`)
  - **credentials**: Test login email and password (look for sections titled "Test Credentials", "Login Details", "Environment", or similar)
- Also check issue labels for environment hints (e.g., `qa3`, `staging`, `prod`)
- If found, include them in `environment_details` in the output
- If not found, set `environment_details` to `null` — the orchestrator handles the fallback

### Step 2: Gap Analysis

Score each validation area (0 or 1). **Be consistent and fair:** if the Jira issue has real requirements, award points where they are present. A score of 0 across all areas should only happen when the issue has almost no usable description or requirements.

1. **Acceptance Criteria Clarity** (1 point)
   - Award **1** if the description contains testable requirements (bullets, numbered list, or clear “when X then Y” statements). Do not require a formal “Acceptance Criteria” header.
   - Can each be verified with pass/fail? Are they specific enough to test (not vague like “should be fast”)?
   - **0** only if there is no testable requirement in the issue.

2. **Edge Cases Coverage** (1 point)
   - Award **1** if boundary conditions, error states, empty/null behavior, or “what if” scenarios are mentioned or can be inferred from the feature (e.g. duplicate → “empty cart”, “same asset twice”).
   - **0** only if the issue is purely happy-path with no mention of errors or edge behavior.

3. **Dependencies Identified** (1 point)
   - Award **1** if linked issues, upstream/downstream systems, APIs, or integrations are listed or referenced.
   - **0** only if there are clearly no dependencies mentioned and none are obvious.

4. **Test Data Needs** (1 point)
   - Award **1** if test data, user roles, permissions, or environment needs are specified or can be inferred (e.g. “user with cart access”, “fulfillment cart with rows”).
   - **0** only if there is no hint of data or environment needs.

5. **Non-Functional Requirements** (1 point)
   - Award **1** if performance, security, or accessibility are mentioned. Optional for many stories.
   - **0** if not mentioned — many valid stories omit NFRs.

**Total Score: 0-5.** Avoid giving 0/5 when the issue has a clear summary, description, and at least some testable requirements; such issues should usually score at least 1–2.

### Step 3: Decision Gate

The threshold is configurable. Use `gap_score_threshold` from:
- User or orchestrator instructions in Chainlit (if provided)
- Else `.github/skills/planner/config.yml`
- Else default **2**

- Score >= threshold → `PROCEED` to Qase Designer
- Score < threshold → `STOP` and generate gap report

### Step 4: Output for PROCEED (required for good test coverage)

When **status** is **PROCEED**, your output JSON **MUST** include the following from the Jira issue you already fetched (Step 1). The Qase Designer uses these to create test cases that cover the story; if they are missing, coverage will be generic and poor.

- **summary** (string): The issue summary/title — feature scope for the designer.
- **acceptance_criteria** (array of strings): Parsed from description or custom fields. Each item becomes a source for test cases.
- **edge_cases** (array of strings): Boundary conditions, error states, empty/null cases you identified.
- **dependencies** (array of strings): Upstream/downstream or test data dependencies.
- **test_data_needs** (array of strings): User roles, data prerequisites, environment needs.

Do not omit these when proceeding. Copy them from the Jira issue response into your final JSON output.

**When status is STOP:** You must still include `summary`, `acceptance_criteria`, `edge_cases`, `dependencies`, `test_data_needs` in your output (from the Jira issue you already fetched). The output file may be used later by qase-designer; without these fields, test cases will be generic and wrong.

## Checklist Reference

Always read and follow: `.github/skills/planner/gap-analysis-checklist.md`
