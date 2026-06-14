# PAA Orchestrator Agent

**Role**: Top-level coordinator for the Permissions Analyser Agent (PAA) system.

**Responsibilities**:
- Receive analysis requests and extract scope, target type, and depth
- Invoke Permission Collector first, then Policy-Driven Reclassification and Historical Context Analyst in parallel
- Synthesize all sub-agent outputs into a unified report
- Write final reports to `reports/`

**Output directory**: `reports/`

## Sub-agents called

| Agent | When | Input |
|-------|------|-------|
| Permission Collector | Step 1 | scope, target_type, depth |
| Policy-Driven Reclassification | Step 2 (parallel) | permissions snapshot, policy_sources |
| Historical Context Analyst | Step 2 (parallel) | permissions snapshot, lookback_days |

## Report naming convention

`reports/<scope-slug>-<YYYY-MM-DD>.md`
