# PAA — System Design

PAA (Permissions Analyser Agent) is a four-agent Claude Code system that takes a
SaaS/cloud vendor, collects its permission catalog, re-rates each permission against
security policy and institutional precedent, and emits a risk-ranked report. The
design's organizing principle is **separation of evidence sources**: the vendor's own
rating, the policy-derived rating, and the historical analyst consensus are computed by
*different* agents and only reconciled at the end, so no single source can silently
dominate.

> See also: [`architecture.md`](architecture.md) for the Mermaid dataflow diagram and
> [`README.md`](README.md) for setup and run instructions.

---

## 1. Component map

| Component | Type | Job |
|---|---|---|
| **PAA Orchestrator** (`.claude/agents/paa-orchestrator.md`) | Claude sub-agent (Sonnet 4.6) | Intake, coordination, synthesis, report writing. Never collects or classifies itself. |
| **Permission Collector** (`.claude/agents/permission-collector.md`) | Claude sub-agent | Fetches permissions from SaaS docs / cloud CLI / local files → normalized JSON. |
| **Policy-Driven Reclassification** (`.claude/agents/policy-reclassification.md`) | Claude sub-agent + RAG | Re-rates each permission against NIST/CSA rules. |
| **Historical Context Analyst** (`.claude/agents/historical-context-analyst.md`) | Claude sub-agent + RAG | Surfaces past analyst decisions on similar permissions. |
| **RAG retrievers** (`*/rag/retriever.py`) | Python + ChromaDB | Embedding search over two vector stores. |
| **MCP server** (`mcp-server/server.py`) | FastMCP, 4 tools | Exposes the same RAG pipelines + decision recording to any Claude session. |

The dataflow is a **fan-out / fan-in**:

```
Orchestrator
  → Permission Collector            (sequential)
  → { Policy ‖ History }            (parallel, per permission)
  → Orchestrator synthesis
  → Markdown + HTML report
```

---

## 2. Reasoning loops

Three nested loops:

- **Outer (intake) loop** — Orchestrator Step 1. A strictly serialized Q&A:
  vendor → source type (docs/CLI/files) → URLs → focus scopes → depth → confirm.
  It **blocks all sub-agent spawning until the user explicitly confirms**. This is the
  human-gated entry point.
- **Middle (per-permission) loop** — Step 3. The system was deliberately refactored from
  "evaluate the whole file once" to **sequential per-permission analysis**. For each
  evaluable permission `i/N`, the Orchestrator prints a live progress line, spawns the
  Policy + History pair, waits, applies the decision matrix, prints the result, and
  accumulates into `all_findings[]` / `all_hints[]`. This trades latency (up to `2N`
  agent calls) for traceability — each permission gets an isolated, inspectable verdict.
- **Inner (retrieval → trigger) loop** — inside the Policy agent. Per permission:
  embed → retrieve top-K rules → tag each as confirmed/speculative → evaluate each rule's
  structured triggers → take the highest-severity *fired* rule → compute the
  reclassification delta.

---

## 3. Memory

Three distinct tiers:

- **Working memory** — the Orchestrator's in-context `all_findings[]` and `all_hints[]`
  lists, accumulated across the per-permission loop and discarded after the report.
- **Artifact memory (filesystem)** — every stage persists: raw snapshots (`snapshots/`,
  verbatim vendor text as an audit record), normalized permissions (`normalized/`),
  findings (`findings/`), historical analysis (`analysis/`), reports (`reports/`).
  Snapshots are written *before* normalization specifically so the original is
  recoverable.
- **Institutional memory (vector store)** — `paa_analyst_decisions` in ChromaDB. This is
  the system's long-term learning substrate: analyst decisions recorded after one run
  become retrievable precedents in the next. It is append-only-with-overwrite-guard and
  carries TTLs (see [Guardrails](#8-guardrails)).

---

## 4. Tools

- **Claude-native tools** are scoped by least privilege: the Orchestrator gets `Agent`
  (to spawn) but not `Bash`; the Collector gets `WebFetch` + `Bash`; Policy/History get
  `Bash` (to call retrievers) but **not** `Agent` (they cannot spawn or recurse).
- **Python RAG tools** — `retriever.py` (stdin permission JSON → stdout ranked
  rules/decisions), `indexer.py`, `config.py`. Agents invoke these via `subprocess` with
  the permission serialized as a literal, explicitly to avoid Windows shell-quoting
  issues.
- **MCP tools** (`server.py`, FastMCP over stdio): `paa_store_status`,
  `paa_retrieve_policy_rules`, `paa_retrieve_decisions`, `paa_record_decision`. These let
  *any* Claude session — not just the orchestrated run — hit the same pipelines (e.g. a
  one-off "what would policy say about this permission" without booting the whole agent
  tree).

---

## 5. Retrieval (RAG)

Two independent ChromaDB collections with identical mechanics:

- **Embedding**: `all-MiniLM-L6-v2`, fully offline/local.
- **Query construction**: `permission_to_query()` flattens a structured permission into
  natural language (`"action types: … actions: … scope level: … manages user
  permissions. org level scope. risk rating: …"`), deliberately mirroring how rules are
  embedded so the vector spaces are comparable.
- **Distance → similarity**: cosine, `similarity = 1 − distance`; anything below
  `SIMILARITY_THRESHOLD = 0.25` is discarded at the retriever.
- **Two-stage relevance gating** (Policy agent's key refinement): retrieved rules are
  re-partitioned by score — `< 0.65 = speculative` (topically adjacent, flagged, never
  produces a confident reclassification), `≥ 0.65 = confirmed`. This prevents the classic
  RAG failure of a loosely-related rule driving a HIGH rating. If *every* fired rule is
  speculative, direction becomes `insufficient_evidence` → surfaced as a **policy gap**,
  not a finding.
- **Corpus**: ~40 rules across NIST SP 800-53 / 207 / 171 and CSA CCM v4 (IAM, data
  security, control-plane).

---

## 6. Structured ("tree-of-thought") reasoning

PAA does not run a literal generative tree-of-thought search; it implements the same
*branch-and-reconcile* idea deterministically:

- Each permission spawns **two independent reasoning branches** (policy vs. history) that
  never see each other's output.
- The branches are reconciled by an explicit **decision matrix** (Step 4b) keyed on
  `(policy_direction × historical_consensus)` → one of `strong_upgrade`, `conflicting`,
  `policy_upgrade`, `vendor_confirmed`, `contextual_downgrade`, `policy_downgrade`,
  `policy_gap`.
- A second matrix (Step 4b-ii) computes `evidence_strength` ∈
  {`strong`, `policy_only`, `history_only`, `weak`, `conflicting`}.
- A **gate** sits on top: `strong_upgrade` is only allowed if (confirmed rule ≥ 0.75)
  AND (high-confidence historical upgrade) AND (`normalization_confidence` ≥ 0.70);
  otherwise it is forcibly downgraded to `policy_upgrade` with a recorded reason. The
  strongest claim is the hardest to assert — the reasoning tree prunes its own most
  aggressive branch unless three independent signals agree.

> **Caveat:** this is structured branch-and-reconcile via explicit decision matrices and
> confidence gates, *not* a generative ToT search with sampling and backtracking. Literal
> ToT (multiple sampled reasoning paths per permission, scored and pruned) is not present
> and would be a genuine addition.

---

## 7. Multi-agent coordination

- **Pure delegation**: the Orchestrator is forbidden from collecting data, applying
  policy, or searching decisions itself — enforced socially by the prompt and
  structurally by its tool set (no `Bash`, no RAG access).
- **Sequential-then-parallel**: the Collector must finish first (everything downstream
  needs the normalized file); then Policy and History run as **two simultaneous `Agent`
  calls in one response**, per permission.
- **Single-focus contracts**: both downstream agents accept `focus_permission_id`,
  evaluate *only* that entry, return JSON inline, and are explicitly told **not to write
  files**. The Orchestrator owns all aggregate file writes. This keeps the parallel
  branches stateless and idempotent.
- **No agent-to-agent communication** — coordination is strictly hub-and-spoke through
  the Orchestrator, preventing cross-contamination of the independent evidence sources.

---

## 8. Guardrails

The most developed part of the system:

- **Count-integrity gate** (`snapshot_count_check`): if a normalized file's entry count
  ≠ its snapshot count, the file is *excluded entirely* from downstream agents and logged
  as a collection error — mismatched counts mean lost/duplicated entries.
- **Confidence partitioning**: entries with `normalization_confidence < 0.75` are never
  fed to RAG (ambiguous input → "confidently wrong findings"); `< 0.70` are flagged
  `unverified`. Low-confidence entries are *forced* into a mandatory "Errors & Gaps"
  report section so they cannot silently vanish.
- **Speculative-match firewall** — the 0.65 confirmed/speculative threshold (§5).
- **`strong_upgrade` triple-gate** (§6).
- **Decision TTL**: every recorded decision gets `review_due = +180 days`; expired
  decisions are dropped from consensus but kept in `matched_decisions` for audit
  visibility.
- **Duplicate guard**: `paa_record_decision` refuses to write a second decision for the
  same `permission_id` unless `override=true`.
- **Fallback**: if the RAG retriever is unreachable, the Policy agent falls back to 5
  built-in rules and sets `rag_enabled: false`, which the Orchestrator must flag in the
  Executive Summary.

---

## 9. Logging

- **Append-only audit log** (`historical-context-analyst/decisions/audit.log`): one JSON
  line per recorded decision (timestamp, decision_id, permission_id, analyst, rating,
  override flag, batch file).
- **Live progress logging** to the user during the per-permission loop (`🔍 [i/N]`
  announce → `✅ [i/N]` result with signal/evidence/history).
- **Persisted artifacts** at every stage double as a forensic trail
  (raw snapshot → normalized → findings → analysis → report).
- `paa_store_status` exposes operational telemetry: rule/decision counts, audit entry
  count, last-recorded timestamp, expired count, and signal coverage.

---

## 10. Evaluation

PAA instruments its *own* analysis quality:

- A **mandatory Evaluation Metrics table** in every report: permissions analysed,
  unverified count, mean normalization confidence, policy coverage %, historical coverage
  %, evidence-strength histogram, policy-gap count, expired decisions excluded.
- **Self-monitoring warning**: if fewer than 10 stored decisions carry an
  `orchestrator_signal`, both the report and `paa_store_status` warn that
  evidence-strength tracking is statistically unreliable — the system flags when it does
  not yet have enough institutional data to trust itself.
- `evidence_strength` per permission is itself an evaluation signal (how much
  corroboration backs each verdict).

---

## 11. Human intervention

Explicitly human-in-the-loop at three points:

- **Before the run** — the blocking intake/confirm gate (no spawning until the analyst
  confirms). Typical decisions surfaced here: reuse an existing snapshot vs. re-collect,
  and scope (analyse all permissions vs. a focus subset).
- **During** — the live progress lines and the dedicated **Conflicting Signals** report
  section, which for each conflict spells out *stakes framing*: worst case if policy is
  right and it is accepted, worst case if history is right and it is upgraded, and the
  minimum action to resolve. The system deliberately does **not** auto-resolve conflicts
  — it routes them to the human.
- **After** — `/paa-record-decision` (or the `paa_record_decision` MCP tool) captures the
  analyst's final call + rationale + confidence, which re-indexes into the decision store
  and becomes precedent for the next run. This closes the learning loop: **human judgment
  is the training signal.**

---

## Appendix — normalized permission schema (key fields)

All collected permissions conform to
`permission-collector/schema/normalized_permission_schema.json` (schema v2.0):

- `normalization_confidence` — float 0.0–1.0; `< 0.75` excluded from policy RAG,
  `< 0.70` flagged `normalization_status: "unverified"`.
- `risk_rating_by_vendor` — strictly vendor-sourced; `UNRATED` when the vendor publishes
  no rating. Used as the reclassification baseline when present.
- `risk_rating_collector` — always PAA-derived; the baseline when the vendor is `UNRATED`.
- `resource_scope` — array (PAA equivalent of the vendor's resource field).
- `snapshot_count_check` — integrity gate; mismatch excludes the file from downstream
  agents.
