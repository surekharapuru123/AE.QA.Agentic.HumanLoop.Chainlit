# Gap Analysis Checklist

## Step 1 - Jira Fetching

- [ ] Fetched issue using `getJiraIssue` with correct `cloudId` and `issueIdOrKey`
- [ ] Extracted summary/title from `fields.summary`
- [ ] Extracted and parsed description from `fields.description`
- [ ] Identified acceptance criteria (from description or custom fields)
- [ ] Listed all attachments from `fields.attachment`
- [ ] Fetched linked issues using `searchJiraIssuesUsingJql`
- [ ] Extracted labels and components
- [ ] Documented business rules found in the issue

## Step 2 - Gap Analysis Scoring

### Acceptance Criteria Clarity (0 or 1)
- [ ] Checked: Are criteria written as testable statements?
- [ ] Checked: Can each be verified with a clear pass/fail?
- [ ] Checked: Are they measurable and specific (not vague)?
- [ ] **Score assigned**: ___

### Edge Cases Coverage (0 or 1)
- [ ] Checked: Are boundary conditions mentioned?
- [ ] Checked: Are error/failure states described?
- [ ] Checked: Are empty, null, and default states covered?
- [ ] **Score assigned**: ___

### Dependencies Identified (0 or 1)
- [ ] Checked: Are upstream/downstream dependencies listed?
- [ ] Checked: Are API contracts or interfaces defined?
- [ ] Checked: Are third-party integrations documented?
- [ ] **Score assigned**: ___

### Test Data Needs (0 or 1)
- [ ] Checked: Are test data requirements specified?
- [ ] Checked: Are user roles and permissions defined?
- [ ] Checked: Are environment prerequisites documented?
- [ ] **Score assigned**: ___

### Non-Functional Requirements (0 or 1)
- [ ] Checked: Are performance expectations stated?
- [ ] Checked: Are security considerations mentioned?
- [ ] Checked: Are accessibility requirements included?
- [ ] **Score assigned**: ___

### Total Gap Score
- [ ] **Calculated total score**: ___ / 5
- [ ] **Note:** 0/5 should be rare (e.g. empty or non-functional issue). If the issue has a clear description and testable requirements, award at least 1 for Acceptance Criteria and 1 for Edge Cases when applicable.

## Step 3 - Decision Gate 1

- [ ] Read threshold from user/orchestrator (`gap_score_threshold`) if provided, else `.github/skills/planner/config.yml`, else default **2**
- [ ] If score >= threshold: Set status to `PROCEED`, generate structured output for Qase Designer
- [ ] If score < threshold: Set status to `STOP`, generate detailed gap report
- [ ] If STOP: Posted gap report as Jira comment using `addCommentToJiraIssue`
- [ ] If STOP: Clearly stated test case generation cannot proceed
- [ ] Output JSON generated with all required fields
