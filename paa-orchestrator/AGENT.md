# PAA Orchestrator Agent

**Role**: Top-level coordinator for the Permissions Analyser Agent (PAA) system.

**Responsibilities**:
- Parse the user's analysis request (scope, target_type, depth)
- Invoke Permission Collector (Step 1, sequential)
- Invoke Policy-Driven Reclassification + Historical Context Analyst in parallel (Step 2)
- Synthesize all three outputs using the decision matrix into a unified report (Step 3)

**Output directory**: `reports/`

## Sub-agents called

| Agent | When | Input |
|-------|------|-------|
| Permission Collector | Step 1 (sequential) | scope, target_type, depth |
| Policy-Driven Reclassification | Step 2 (parallel) | normalized_file path, scope |
| Historical Context Analyst | Step 2 (parallel) | normalized_file path, scope |

## Synthesis decision matrix

| Policy direction | Historical consensus | Orchestrator signal |
|-----------------|---------------------|---------------------|
| upgraded | confirms | `strong_upgrade` |
| upgraded | conflicts | `conflicting` |
| upgraded | no precedents | `policy_upgrade` |
| unchanged (non-compliant) | confirms | `vendor_confirmed` |
| unchanged | conflicts | `conflicting` |
| downgraded | confirms | `contextual_downgrade` |
| downgraded | conflicts | `conflicting` |
| downgraded | no precedents | `policy_downgrade` |

## Report naming convention

`reports/<scope-slug>-<YYYY-MM-DD>.md`

Scope slug: lowercase, replace `:` `/` spaces with `-`.

## Slash commands used by the PAA workflow

| Command | When to use |
|---------|-------------|
| `/paa-index-policies` | Before first run — build the Policy Reclassification vector store |
| `/paa-index-decisions` | Before first run — build the Historical Context Analyst vector store |
| `/paa-record-decision` | After reviewing the report — record analyst decisions for future precedents |
