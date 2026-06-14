"""
Retriever for the PAA Historical Context Analyst RAG pipeline.

Accepts a single normalized permission entry as JSON on stdin, queries ChromaDB
for the TOP_K most semantically similar past analyst decisions, and writes the
results as JSON to stdout.

Usage (from project root):
    echo '<permission_json>' | python historical-context-analyst/rag/retriever.py
    python historical-context-analyst/rag/retriever.py --top-k 3
    python historical-context-analyst/rag/retriever.py --query "s3 PutBucketPolicy role resource"

Exit codes:
    0  — results returned (may be empty if nothing meets threshold)
    1  — ChromaDB collection not found (run indexer.py first)
    2  — bad input JSON
"""
import argparse
import json
import sys
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    VECTOR_STORE_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    TOP_K,
    SIMILARITY_THRESHOLD,
)


def permission_to_query(permission: dict) -> str:
    """
    Build a natural-language query from a normalised permission entry.
    Mirrors decision_to_text() in indexer.py so embeddings are comparable.
    """
    parts = []

    source_type = permission.get("source_type", "")
    if source_type:
        parts.append(f"source type: {source_type}")

    action_type = permission.get("action_type", {})
    active = [k for k, v in action_type.items() if v is True]
    if active:
        parts.append(f"action types: {', '.join(active)}")

    actions = permission.get("actions", [])
    if actions:
        parts.append(f"actions: {', '.join(str(a) for a in actions)}")

    scope = permission.get("scope_level", "")
    if scope:
        parts.append(f"scope level: {scope}")

    principal_type = permission.get("principal_type", "")
    if principal_type:
        parts.append(f"principal type: {principal_type}")

    effect = permission.get("effect", "")
    if effect:
        parts.append(f"effect: {effect}")

    if permission.get("manages_user_permissions"):
        parts.append("manages user permissions")

    if permission.get("is_org_level"):
        parts.append("org level scope")

    risk = permission.get("risk_rating_by_vendor", "")
    if risk:
        parts.append(f"vendor risk rating: {risk}")

    return ". ".join(parts)


def retrieve(permission: dict, top_k: int = TOP_K) -> dict:
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)

    try:
        client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
        collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
    except Exception as exc:
        print(
            json.dumps({"error": f"Collection not found — run indexer.py first. ({exc})"}),
            file=sys.stderr,
        )
        sys.exit(1)

    query_text = permission_to_query(permission)

    results = collection.query(
        query_texts=[query_text],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    matched_decisions = []
    for i, doc_id in enumerate(results["ids"][0]):
        distance   = results["distances"][0][i]
        similarity = round(1.0 - distance, 4)

        if similarity < SIMILARITY_THRESHOLD:
            continue

        meta = results["metadatas"][0][i]
        matched_decisions.append({
            "rank":                    i + 1,
            "similarity_score":        similarity,
            "decision_id":             meta.get("decision_id", ""),
            "batch_id":                meta.get("batch_id", ""),
            "decided_at":              meta.get("decided_at", ""),
            "analyst":                 meta.get("analyst", ""),
            "source_type":             meta.get("source_type", ""),
            "actions":                 json.loads(meta.get("actions_json", "[]")),
            "principal_type":          meta.get("principal_type", ""),
            "scope_level":             meta.get("scope_level", ""),
            "manages_user_permissions": meta.get("manages_user_permissions", "False") == "True",
            "vendor_rating":           meta.get("vendor_rating", ""),
            "policy_severity":         meta.get("policy_severity", ""),
            "analyst_final_rating":    meta.get("analyst_final_rating", ""),
            "override_direction":      meta.get("override_direction", ""),
            "rationale":               meta.get("rationale", ""),
            "compensating_controls":   json.loads(meta.get("compensating_controls_json", "[]")),
            "chunk_text":              results["documents"][0][i],
        })

    return {
        "permission_id":      permission.get("id", ""),
        "query":              query_text,
        "top_k_requested":    top_k,
        "decisions_returned": len(matched_decisions),
        "matched_decisions":  matched_decisions,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieve similar past analyst decisions for a permission entry.")
    parser.add_argument("--top-k", type=int, default=TOP_K, help="Max decisions to return.")
    parser.add_argument("--query", type=str, default=None, help="Raw query string (skips permission parsing).")
    args = parser.parse_args()

    if args.query:
        permission = {"id": "manual-query", "actions": [args.query]}
    else:
        raw = sys.stdin.read().strip()
        if not raw:
            print(json.dumps({"error": "No input received on stdin."}), file=sys.stderr)
            sys.exit(2)
        try:
            permission = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"Invalid JSON on stdin: {exc}"}), file=sys.stderr)
            sys.exit(2)

    result = retrieve(permission, top_k=args.top_k)
    print(json.dumps(result, indent=2))
