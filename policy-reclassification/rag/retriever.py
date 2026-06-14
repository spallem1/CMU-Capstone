"""
Retriever for the PAA Policy-Driven Reclassification RAG pipeline.

Accepts a single permission entry as JSON on stdin, queries ChromaDB for the
TOP_K most semantically similar policy rules, and writes the results as JSON
to stdout for the Policy-Driven Reclassification Agent to consume.

Usage (from project root):
    echo '<permission_json>' | python policy-reclassification/rag/retriever.py
    python policy-reclassification/rag/retriever.py --query "admin wildcard s3 resource"
    python policy-reclassification/rag/retriever.py --top-k 8  (override TOP_K)

Exit codes:
    0  — results returned (may be empty list if nothing meets threshold)
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
    Build a natural-language query string from a normalised permission entry.
    Mirrors the language used in rule_to_text() so embeddings are comparable.
    """
    parts = []

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

    resource = permission.get("resource", "")
    if resource:
        parts.append(f"resource: {resource}")

    if permission.get("manages_user_permissions"):
        parts.append("manages user permissions")

    if permission.get("is_org_level"):
        parts.append("org level scope")

    risk = permission.get("risk_rating_by_vendor", "")
    if risk:
        parts.append(f"risk rating: {risk}")

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

    retrieved_rules = []
    for i, doc_id in enumerate(results["ids"][0]):
        distance  = results["distances"][0][i]
        similarity = round(1.0 - distance, 4)       # cosine: distance = 1 - similarity

        if similarity < SIMILARITY_THRESHOLD:
            continue

        meta = results["metadatas"][0][i]

        retrieved_rules.append({
            "rank":                  i + 1,
            "similarity_score":      similarity,
            "rule_id":               meta.get("rule_id", ""),
            "rule_name":             meta.get("rule_name", ""),
            "policy_id":             meta.get("policy_id", ""),
            "policy_name":           meta.get("policy_name", ""),
            "standard":              meta.get("standard", ""),
            "control_ref":           meta.get("control_ref", ""),
            "classification":        meta.get("classification", ""),
            "severity":              meta.get("severity", ""),
            "rationale":             meta.get("rationale", ""),
            "remediation":           meta.get("remediation", ""),
            "compensating_controls": json.loads(meta.get("compensating_controls", "[]")),
            "triggers":              json.loads(meta.get("triggers_json", "{}")),
            "source_file":           meta.get("source_file", ""),
            "chunk_text":            results["documents"][0][i],
        })

    return {
        "permission_id":   permission.get("id", ""),
        "query":           query_text,
        "top_k_requested": top_k,
        "rules_returned":  len(retrieved_rules),
        "retrieved_rules": retrieved_rules,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieve relevant policy rules for a permission entry.")
    parser.add_argument("--top-k", type=int, default=TOP_K, help="Max rules to return.")
    parser.add_argument("--query", type=str, default=None, help="Raw query string (skips permission parsing).")
    args = parser.parse_args()

    if args.query:
        # Direct string query mode — useful for testing
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
