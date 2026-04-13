# Agent Output Schema Validation Rules

## Universal Required Fields

Every agent output MUST be valid JSON containing at minimum:

```json
{
  "agent": "<agent-name>",
  "status": "PROCEED | STOP | COMPLETE"
}
```

## Per-Agent Schema

### Planner Agent

Required when `status` is `PROCEED`:
- `jira_key` (string)
- `gap_score` (number, must be >= configurable threshold, default 2)
- `summary` (string)
- `acceptance_criteria` (string[])
- `edge_cases` (string[])
- `dependencies` (string[])
- `test_data_needs` (string[])
- `environment_details` (object or null) — extracted from the Jira issue; `null` if not found
  - `base_url` (string or null) — application URL to test
  - `credentials` (object or null) — `{ email, password }` for login

Required when `status` is `STOP`:
- `gap_score` (number, < 2)
- `gap_report` (object with failing areas and recommendations)
- `summary`, `acceptance_criteria`, `edge_cases`, `dependencies`, `test_data_needs` (same as PROCEED — always include so qase-designer can use the file if run later)

### Qase Designer Agent

Required when `status` is `PROCEED`:
- `project_code` (string)
- `suite_id` (number)
- `plan_id` (number)
- `member` (object: `member_id`, `name`, `email`)
- `test_cases` (array of objects)
- `automatable_case_ids` (number[], non-empty)
- `manual_case_ids` (number[])

### Automation Agent

Required (always `COMPLETE`):
- `test_dir` (string, path to test directory, e.g. `tests/gps-login`)
- `scripts` (array with `case_id`, `file_path`, `page_objects`)
- `total_scripts` (number)
- `project_code` (string)
- `plan_id` (number)
- `suite_id` (number)
- `automatable_case_ids` (number[], propagated from Qase Designer input — required by Executor to create Qase run)

Recommended when GitHub push succeeds (Automation → Executor → Healer handoff):
- `branch` (string) — feature branch containing generated tests, e.g. `qa/e2e-PROJ-123-feature-slug`
- `pr_url` (string | null)
- `pr_number` (number | null)

Omit only if GitHub was unavailable; document limitations in narrative output.

### Executor Agent

Required (always `COMPLETE`):
- `run_id` (number) — from Qase MCP **`create_run`** response only; never a placeholder string
- `project_code` (string)
- `executed_by` (object: `member_id`, `name`, `email`)
- `artifact_paths` (object: `scripts` string[], `pages` string[] optional, optional `note`) — repo-relative paths copied from Automation output
- `summary` (object: `total`, `passed`, `failed`, `skipped`, `pass_rate`, `execution_time_ms`)
- `failures` (array, may be empty)

Also include `results_reported` (array) when reporting per-case outcomes to Qase.

Recommended:
- `git_branch` (string) — branch actually checked out for execution (normally same as Automation `branch`)

### Healer Agent

Required (always `COMPLETE`):
- `actions` (array with `case_id`, `category`, `action`, `detail`)
- `summary` (object: `self_healed`, `defects_created`, `data_corrections_needed`)

Optional fields per action (include when applicable):
- `jira_key` (string) — present when `action` is `jira_defect_created`
- `qase_defect_id` (number) — present when `action` is `jira_defect_created`
- `rerun_status` (string: passed/failed) — present when `action` is `self_healed`

Recommended when script fixes were pushed:
- `git_branch` (string), `pr_url` (string | null), `pushed_healing_commits` (boolean)

## Validation Behavior

- If a required field is missing, the agent MUST add it before returning
- If `status` value doesn't match the expected values, the agent MUST correct it
- The orchestrator (parent agent) MUST validate the output before passing it to the next stage
- Never pass partial or malformed JSON between pipeline stages
