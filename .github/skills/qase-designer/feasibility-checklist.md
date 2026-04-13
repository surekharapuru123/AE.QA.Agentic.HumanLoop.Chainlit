# Automation Feasibility Checklist

## Step 4 - Feasibility Assessment

For **each** test case, evaluate the following criteria:

### Criterion 1: Stable UI/API
- [ ] Is the feature's UI/API unlikely to change frequently?
- [ ] Are selectors or endpoints stable and well-defined?
- [ ] Is the feature past the active development phase?

### Criterion 2: No Heavy Manual Validation
- [ ] Can the expected result be verified programmatically?
- [ ] No visual/subjective validation required (e.g., "looks correct")?
- [ ] No CAPTCHA or human-verification steps?

### Criterion 3: Deterministic Outcome
- [ ] Same input always produces the same output?
- [ ] No randomized or time-dependent behavior?
- [ ] No external dependencies that vary between runs?

### Criterion 4: Data Manageable
- [ ] Test data can be created/seeded programmatically?
- [ ] No manual data setup required before each run?
- [ ] Data cleanup/teardown can be automated?

### Scoring
- [ ] All 4 criteria met → Score = 1 (automatable)
- [ ] Any criterion fails → Score = 0 (manual only)
- [ ] Updated each case via `update_case` with **`automation` as integer** `1` (feasible) or `0` (not feasible) when the API rejects string values

## Step 5 - Decision Gate 2

- [ ] Counted total automatable cases (score = 1)
- [ ] Counted total manual-only cases (score = 0)
- [ ] If automatable count ≥ 1: Set status to `PROCEED`
- [ ] If automatable count = 0: Set status to `STOP`
- [ ] Generated output JSON with case IDs split by automation status
