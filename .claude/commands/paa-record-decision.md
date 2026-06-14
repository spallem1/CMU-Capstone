# /paa-record-decision

Record the current IAM analyst's final decisions on a completed PAA analysis run.
Writes a new decision batch to `historical-context-analyst/decisions/` and re-indexes
the decision store so future analyses can learn from these decisions.

## When to run
After reviewing the PAA Orchestrator report and making your final call on each
reclassified permission — confirm, upgrade, downgrade, or accept vendor rating.

## Arguments
- `--findings <path>` — Path to a specific reclassification findings file
  (default: most recent file in `policy-reclassification/findings/`)
- `--analyst <email>` — Analyst email to record (default: prompt the user)

## Steps

Run the following steps in order. Stop and report clearly if any step fails.

### 1. Locate the findings file

If `--findings` was provided, use that path.

Otherwise, find the most recent reclassification findings file:
```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import pathlib
files = sorted(pathlib.Path('policy-reclassification/findings').glob('*.json'))
if not files:
    print('NO_FILES')
else:
    print(files[-1])
"
```

If no findings file exists, stop and tell the user to run a PAA analysis first.

### 2. Read the findings file

Use the Read tool to load the findings file. Extract:
- `scope` — for naming the decision batch
- `findings[]` — the list of permission findings to review
- Focus on findings where `reclassification.delta == true` (vendor and policy disagree)
  and findings where `classification != "compliant"` — these need analyst decisions

### 3. Determine the analyst email

If `--analyst <email>` was provided, use it.
Otherwise, ask the user: "What is your email address for this decision record?"

### 4. Present each non-compliant finding for analyst review

For each finding where `classification != "compliant"`:

Present to the user:
```
Permission: <permission_id>
Principal:  <principal>
Actions:    <actions>
Scope:      <scope_level>

Vendor rating:   <reclassification.vendor_rating>
Policy severity: <reclassification.policy_severity>
Direction:       <reclassification.direction>

Triggered rules: <rule_id> — <rule_name> (<severity>)
Recommendation:  <recommendation>

Historical hints (if any from Historical Context Analyst output):
  <hint text>

Your decision:
  [1] Confirm policy severity (<policy_severity>)
  [2] Upgrade to <next severity>
  [3] Downgrade to <previous severity>
  [4] Accept vendor rating (<vendor_rating>)
  [5] Skip (do not record)
```

Wait for the user's choice and rationale before proceeding to the next finding.

### 5. Build the decision batch

Collect all decisions the analyst provided (skipped findings are excluded).
Build a JSON batch in this format:

```json
{
  "batch_id": "<scope-slug>-<YYYY-MM-DD>",
  "source_type": "<from the normalized file source_type>",
  "review_scope": "<scope>",
  "created_at": "<ISO 8601 timestamp>",
  "decisions": [
    {
      "decision_id": "dec-<scope-slug>-<NNN>",
      "decided_at": "<ISO 8601 timestamp>",
      "analyst": "<email>",
      "permission_pattern": {
        "source_type": "<source_type>",
        "actions": ["<action>"],
        "principal_type": "<principal_type>",
        "scope_level": "<scope_level>",
        "manages_user_permissions": "<bool>",
        "effect": "<allow|deny>",
        "action_type": { "<key>": "<bool>" }
      },
      "vendor_rating": "<vendor_rating>",
      "policy_severity": "<policy_severity>",
      "analyst_final_rating": "<analyst chosen rating>",
      "override_direction": "<upgrade|downgrade|confirmed|accepted>",
      "rationale": "<analyst rationale>",
      "compensating_controls": ["<any controls the analyst mentioned>"]
    }
  ]
}
```

`override_direction` mapping:
- analyst chose higher than `policy_severity` → `"upgrade"`
- analyst chose lower than `policy_severity` → `"downgrade"`
- analyst agreed with `policy_severity` (which differed from vendor) → `"confirmed"`
- analyst reverted to `vendor_rating` → `"accepted"`

### 6. Write the decision file

Write the batch JSON to:
```
historical-context-analyst/decisions/<batch_id>.json
```

Confirm the file was written and show the path.

### 7. Re-index the decision store

```bash
cd "$(git rev-parse --show-toplevel)" && python historical-context-analyst/rag/indexer.py
```

This adds only the new decisions (idempotent — existing ones are skipped).
Display the indexer output showing how many new decisions were added.

## Report

After all steps complete, summarise:
- Scope reviewed
- Number of findings presented
- Number of decisions recorded (and how many skipped)
- Decision breakdown: upgrades / downgrades / confirmed / accepted
- Decision file written to: `<path>`
- Decision store now contains: `<N>` total decisions
