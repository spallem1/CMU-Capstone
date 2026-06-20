"""
PAA MCP Server

Exposes the PAA RAG pipelines as MCP tools so any Claude Code session can
retrieve policy rules and analyst decisions without running the full agent
pipeline locally.

Tools:
  paa_store_status           — Health check: rule and decision counts
  paa_retrieve_policy_rules  — NIST/CSA rule retrieval for a permission
  paa_retrieve_decisions     — Past analyst decision retrieval for a permission
  paa_record_decision        — Record a new analyst decision and re-index

Prerequisites:
  pip install mcp chromadb sentence-transformers
  /paa-index-policies   — build the policy vector store
  /paa-index-decisions  — build the decision vector store

Registration (run once):
  claude mcp add paa python /absolute/path/to/mcp-server/server.py
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PR_RETRIEVER = PROJECT_ROOT / "policy-reclassification" / "rag" / "retriever.py"
_HC_RETRIEVER = PROJECT_ROOT / "historical-context-analyst" / "rag" / "retriever.py"
_HC_INDEXER   = PROJECT_ROOT / "historical-context-analyst" / "rag" / "indexer.py"
_DECISIONS_DIR = PROJECT_ROOT / "historical-context-analyst" / "decisions"

mcp = FastMCP("PAA — Permissions Analyser Agent")


def _run_retriever(script: Path, permission_json: str, top_k: int) -> str:
    result = subprocess.run(
        [sys.executable, str(script), "--top-k", str(top_k)],
        input=permission_json,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        return json.dumps({"error": result.stderr.strip() or "Retriever failed with no error output."})
    return result.stdout.strip()


@mcp.tool()
def paa_store_status() -> str:
    """
    Return the number of policy rules and analyst decisions indexed in the PAA
    vector stores, plus audit log and expiry metrics. Use this to confirm the
    stores are ready before analysis.
    """
    import chromadb
    from datetime import timedelta

    def _count(store_path: str, collection_name: str) -> dict:
        try:
            client = chromadb.PersistentClient(path=store_path)
            col = client.get_collection(collection_name)
            count = col.count()
            status = "ready" if count > 0 else "empty"
        except Exception as exc:
            count = -1
            status = f"not_found ({exc})"
        return {"count": count, "status": status}

    policy = _count(
        str(PROJECT_ROOT / "policy-reclassification" / "vector_store"),
        "paa_policy_rules",
    )
    decisions = _count(
        str(PROJECT_ROOT / "historical-context-analyst" / "vector_store"),
        "paa_analyst_decisions",
    )

    # Audit log metrics
    audit_log = _DECISIONS_DIR / "audit.log"
    audit_entry_count = 0
    last_decision_recorded = None
    if audit_log.exists():
        try:
            with open(audit_log, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]
            audit_entry_count = len(lines)
            if lines:
                last_entry = json.loads(lines[-1])
                last_decision_recorded = last_entry.get("timestamp")
        except (OSError, json.JSONDecodeError):
            pass

    # Expiry and signal coverage
    today = datetime.now(timezone.utc).date()
    expired_count = 0
    entries_with_signal = 0
    for batch_file in sorted(_DECISIONS_DIR.glob("mcp-*.json")):
        try:
            with open(batch_file, encoding="utf-8") as fh:
                batch = json.load(fh)
            for dec in batch.get("decisions", []):
                review_due = dec.get("review_due")
                if review_due:
                    try:
                        if datetime.strptime(review_due, "%Y-%m-%d").date() < today:
                            expired_count += 1
                    except ValueError:
                        pass
                if dec.get("orchestrator_signal"):
                    entries_with_signal += 1
        except (json.JSONDecodeError, OSError):
            pass

    warnings = []
    if decisions["count"] > 0 and entries_with_signal < 10:
        warnings.append(
            f"Only {entries_with_signal} decision(s) have orchestrator_signal set. "
            "Run /paa-index-decisions after recording more decisions with orchestrator_signal "
            "to improve evidence-strength tracking."
        )

    return json.dumps(
        {
            "project_root": str(PROJECT_ROOT),
            "policy_rules": {"collection": "paa_policy_rules", **policy},
            "analyst_decisions": {
                "collection": "paa_analyst_decisions",
                **decisions,
                "expired_decisions_count": expired_count,
                "entries_with_orchestrator_signal": entries_with_signal,
            },
            "audit_log": {
                "path": str(audit_log.relative_to(PROJECT_ROOT)) if audit_log.exists() else None,
                "entry_count": audit_entry_count,
                "last_decision_recorded": last_decision_recorded,
            },
            "setup_needed": policy["count"] <= 0 or decisions["count"] < 0,
            "warnings": warnings,
        },
        indent=2,
    )


@mcp.tool()
def paa_retrieve_policy_rules(permission_json: str, top_k: int = 5) -> str:
    """
    Retrieve NIST/CSA policy rules semantically similar to a normalized permission entry.

    Returns rules ranked by similarity, each containing: rule_id, rule_name, severity,
    classification, triggers, rationale, remediation, and compensating_controls.

    Args:
        permission_json: JSON string of a normalized permission entry. Required fields:
                         id, actions, action_type (dict of bool), scope_level,
                         principal_type, effect, resource, manages_user_permissions,
                         risk_rating_by_vendor.
        top_k: Maximum number of rules to return (default 5, capped at 10).
    """
    top_k = min(max(1, top_k), 10)
    return _run_retriever(_PR_RETRIEVER, permission_json, top_k)


@mcp.tool()
def paa_retrieve_decisions(permission_json: str, top_k: int = 5) -> str:
    """
    Retrieve past IAM analyst decisions semantically similar to a normalized permission entry.

    Returns decisions ranked by similarity, each containing: decision_id, decided_at,
    analyst, analyst_final_rating, override_direction, rationale, compensating_controls.

    Use this to surface institutional precedents before making a reclassification call.

    Args:
        permission_json: JSON string of a normalized permission entry (same schema as
                         paa_retrieve_policy_rules). source_type is also used for matching.
        top_k: Maximum number of decisions to return (default 5).
    """
    top_k = min(max(1, top_k), 10)
    return _run_retriever(_HC_RETRIEVER, permission_json, top_k)


@mcp.tool()
def paa_record_decision(decision_json: str) -> str:
    """
    Record an IAM analyst's final decision on a permission and index it so future
    analyses can learn from it as a precedent.

    Call this after reviewing policy reclassification results and historical hints,
    once you have made your final rating call.

    Args:
        decision_json: JSON object with these fields:
          Required:
          - permission_id: str       — the id from the normalized permission entry
          - permission: dict         — the normalized permission entry being decided on
          - final_rating: str        — CRITICAL / HIGH / MEDIUM / LOW / INFO
          - decision: str            — approve / escalate / reject
          - rationale: str           — non-empty explanation of the decision
          - analyst_confidence: str  — high / medium / low
          - analyst: str             — analyst email or identifier
          - vendor_rating: str       — the vendor's original risk rating
          - policy_severity: str     — the policy engine's severity
          Optional:
          - override_direction: str  — upgrade / downgrade / confirmed / accepted
          - orchestrator_signal: str — the orchestrator signal that triggered this decision
          - compensating_controls: list[str]
          - override: bool           — set true to overwrite an existing decision for the same permission_id
    """
    from datetime import timedelta

    try:
        payload = json.loads(decision_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON: {exc}"})

    required = {"permission_id", "permission", "final_rating", "decision", "rationale", "analyst_confidence", "analyst", "vendor_rating", "policy_severity"}
    missing = required - payload.keys()
    if missing:
        return json.dumps({"error": f"Missing required fields: {sorted(missing)}"})

    if not str(payload.get("rationale", "")).strip():
        return json.dumps({"error": "rationale must not be empty"})

    valid_decisions = {"approve", "escalate", "reject"}
    if payload["decision"] not in valid_decisions:
        return json.dumps({"error": f"decision must be one of {sorted(valid_decisions)}"})

    valid_confidence = {"high", "medium", "low"}
    if payload["analyst_confidence"] not in valid_confidence:
        return json.dumps({"error": f"analyst_confidence must be one of {sorted(valid_confidence)}"})

    valid_ratings = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
    for field in ("final_rating", "vendor_rating", "policy_severity"):
        val = payload.get(field)
        if val not in valid_ratings:
            return json.dumps({"error": f"{field} must be one of {sorted(valid_ratings)}, got: {val!r}"})

    permission_id = payload["permission_id"]
    override = bool(payload.get("override", False))

    # Duplicate guard: scan existing batch files for same permission_id
    _DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    existing_file = None
    existing_batch = None
    for batch_file in sorted(_DECISIONS_DIR.glob("mcp-*.json")):
        try:
            with open(batch_file, encoding="utf-8") as fh:
                batch_data = json.load(fh)
            for dec in batch_data.get("decisions", []):
                if dec.get("permission_id") == permission_id:
                    if not override:
                        return json.dumps({
                            "error": (
                                f"A decision for permission_id '{permission_id}' already exists "
                                f"in {batch_file.name}. Pass override=true to overwrite."
                            ),
                            "existing_decision_id": dec.get("decision_id"),
                        })
                    existing_file = batch_file
                    existing_batch = batch_data
                    existing_batch["decisions"] = [
                        d for d in existing_batch["decisions"] if d.get("permission_id") != permission_id
                    ]
                    break
        except (json.JSONDecodeError, OSError):
            pass
        if existing_file:
            break

    perm = payload["permission"]
    now = datetime.now(timezone.utc)
    review_due = (now + timedelta(days=180)).date().isoformat()
    month = now.strftime("%Y-%m")
    batch_id = f"mcp-{month}"
    decision_id = f"dec-mcp-{now.strftime('%Y%m%dT%H%M%SZ')}"

    decision = {
        "decision_id": decision_id,
        "permission_id": permission_id,
        "decided_at": now.isoformat(),
        "review_due": review_due,
        "analyst": payload["analyst"],
        "analyst_confidence": payload["analyst_confidence"],
        "final_rating": payload["final_rating"],
        "analyst_final_rating": payload["final_rating"],  # backward compat
        "decision": payload["decision"],
        "permission_pattern": {
            "source_type": perm.get("source_type", ""),
            "actions": perm.get("actions", []),
            "principal_type": perm.get("principal_type", ""),
            "scope_level": perm.get("scope_level", ""),
            "manages_user_permissions": perm.get("manages_user_permissions", False),
            "effect": perm.get("effect", "allow"),
            "action_type": perm.get("action_type", {}),
        },
        "vendor_rating": payload["vendor_rating"],
        "policy_severity": payload["policy_severity"],
        "override_direction": payload.get("override_direction"),
        "orchestrator_signal": payload.get("orchestrator_signal"),
        "rationale": payload["rationale"],
        "compensating_controls": payload.get("compensating_controls", []),
    }

    if existing_file and existing_batch is not None:
        target_file = existing_file
        batch = existing_batch
    else:
        target_file = _DECISIONS_DIR / f"mcp-{month}.json"
        if target_file.exists():
            with open(target_file, encoding="utf-8") as fh:
                batch = json.load(fh)
        else:
            batch = {
                "batch_id": batch_id,
                "source_type": perm.get("source_type", ""),
                "review_scope": "MCP-recorded analyst decisions",
                "created_at": now.isoformat(),
                "decisions": [],
            }

    batch["decisions"].append(decision)

    with open(target_file, "w", encoding="utf-8") as fh:
        json.dump(batch, fh, indent=2)

    # Append to audit log (append-only)
    audit_log = _DECISIONS_DIR / "audit.log"
    audit_entry = {
        "timestamp": now.isoformat(),
        "decision_id": decision_id,
        "permission_id": permission_id,
        "analyst": payload["analyst"],
        "final_rating": payload["final_rating"],
        "decision": payload["decision"],
        "override": override,
        "batch_file": target_file.name,
    }
    with open(audit_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(audit_entry) + "\n")

    # Incremental re-index (idempotent — skips existing IDs)
    index_result = subprocess.run(
        [sys.executable, str(_HC_INDEXER)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    return json.dumps(
        {
            "status": "recorded",
            "decision_id": decision_id,
            "permission_id": permission_id,
            "review_due": review_due,
            "decision_file": str(target_file.relative_to(PROJECT_ROOT)),
            "batch_id": batch_id,
            "decisions_in_batch": len(batch["decisions"]),
            "overwrite": override,
            "indexer": index_result.stdout.strip() or index_result.stderr.strip(),
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
