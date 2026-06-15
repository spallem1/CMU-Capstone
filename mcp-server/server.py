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
    vector stores. Use this to confirm the stores are ready before analysis.
    """
    import chromadb

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

    return json.dumps(
        {
            "project_root": str(PROJECT_ROOT),
            "policy_rules": {"collection": "paa_policy_rules", **policy},
            "analyst_decisions": {"collection": "paa_analyst_decisions", **decisions},
            "setup_needed": policy["count"] <= 0 or decisions["count"] < 0,
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
          - permission: dict  — the normalized permission entry being decided on
          - analyst_final_rating: str  — CRITICAL / HIGH / MEDIUM / LOW / INFO
          - override_direction: str  — one of:
              "upgrade"   (analyst rated higher than policy_severity)
              "downgrade" (analyst rated lower than policy_severity)
              "confirmed" (analyst agreed with policy_severity)
              "accepted"  (analyst reverted to vendor rating)
          - rationale: str  — explanation of the decision
          - analyst: str  — analyst email or identifier
          - vendor_rating: str  — the vendor's original risk rating
          - policy_severity: str  — the policy engine's severity
          - compensating_controls: list[str]  — (optional) controls that justify the rating
    """
    try:
        payload = json.loads(decision_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON: {exc}"})

    required = {"permission", "analyst_final_rating", "override_direction", "rationale", "analyst", "vendor_rating", "policy_severity"}
    missing = required - payload.keys()
    if missing:
        return json.dumps({"error": f"Missing required fields: {sorted(missing)}"})

    valid_directions = {"upgrade", "downgrade", "confirmed", "accepted"}
    if payload["override_direction"] not in valid_directions:
        return json.dumps({"error": f"override_direction must be one of {sorted(valid_directions)}"})

    valid_ratings = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
    for field in ("analyst_final_rating", "vendor_rating", "policy_severity"):
        if payload[field] not in valid_ratings:
            return json.dumps({"error": f"{field} must be one of {sorted(valid_ratings)}, got: {payload[field]!r}"})

    perm = payload["permission"]
    now = datetime.now(timezone.utc).isoformat()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    batch_id = f"mcp-{month}"
    decision_id = f"dec-mcp-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    decision = {
        "decision_id": decision_id,
        "decided_at": now,
        "analyst": payload["analyst"],
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
        "analyst_final_rating": payload["analyst_final_rating"],
        "override_direction": payload["override_direction"],
        "rationale": payload["rationale"],
        "compensating_controls": payload.get("compensating_controls", []),
    }

    _DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    decision_file = _DECISIONS_DIR / f"mcp-{month}.json"

    if decision_file.exists():
        with open(decision_file, encoding="utf-8") as fh:
            batch = json.load(fh)
    else:
        batch = {
            "batch_id": batch_id,
            "source_type": perm.get("source_type", ""),
            "review_scope": "MCP-recorded analyst decisions",
            "created_at": now,
            "decisions": [],
        }

    batch["decisions"].append(decision)

    with open(decision_file, "w", encoding="utf-8") as fh:
        json.dump(batch, fh, indent=2)

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
            "decision_file": str(decision_file.relative_to(PROJECT_ROOT)),
            "batch_id": batch_id,
            "decisions_in_batch": len(batch["decisions"]),
            "indexer": index_result.stdout.strip() or index_result.stderr.strip(),
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
