"""
Indexer for the PAA Historical Context Analyst RAG pipeline.

Reads every JSON file in historical-context-analyst/decisions/, converts each
analyst decision into a searchable text chunk, generates sentence embeddings,
and persists them in a ChromaDB collection.

Usage (from project root):
    python historical-context-analyst/rag/indexer.py
    python historical-context-analyst/rag/indexer.py --reset   # force re-index
"""
import argparse
import json
import sys
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

sys.path.insert(0, str(Path(__file__).parent))
from config import DECISIONS_DIR, VECTOR_STORE_DIR, COLLECTION_NAME, EMBEDDING_MODEL


def decision_to_text(decision: dict, batch: dict) -> str:
    """
    Serialise an analyst decision into a dense natural-language chunk for embedding.
    Mirrors permission_to_query() in retriever.py so embeddings are comparable.
    """
    pattern = decision.get("permission_pattern", {})
    action_type = pattern.get("action_type", {})
    active_types = [k for k, v in action_type.items() if v is True]

    actions = pattern.get("actions", [])
    source_type = pattern.get("source_type", batch.get("source_type", ""))

    parts = [
        f"Source type: {source_type}.",
        f"Actions: {', '.join(actions)}." if actions else "",
        f"Action types: {', '.join(active_types)}." if active_types else "",
        f"Principal type: {pattern.get('principal_type', '')}.",
        f"Scope level: {pattern.get('scope_level', '')}.",
        f"Manages user permissions: {pattern.get('manages_user_permissions', False)}.",
        f"Effect: {pattern.get('effect', 'allow')}.",
        f"Vendor rating: {decision.get('vendor_rating', '')}.",
        f"Policy severity: {decision.get('policy_severity', '')}.",
        f"Analyst final rating: {decision.get('analyst_final_rating', '')}.",
        f"Override direction: {decision.get('override_direction', '')}.",
        f"Rationale: {decision.get('rationale', '')}",
    ]
    return " ".join(p for p in parts if p)


def build_metadata(decision: dict, batch: dict) -> dict:
    """
    Flatten all fields into a ChromaDB-compatible metadata dict (strings only).
    """
    pattern = decision.get("permission_pattern", {})
    return {
        "batch_id":             batch.get("batch_id", ""),
        "source_type":          pattern.get("source_type", batch.get("source_type", "")),
        "decision_id":          decision.get("decision_id", ""),
        "decided_at":           decision.get("decided_at", ""),
        "analyst":              decision.get("analyst", ""),
        "actions_json":         json.dumps(pattern.get("actions", [])),
        "principal_type":       pattern.get("principal_type", ""),
        "scope_level":          pattern.get("scope_level", ""),
        "manages_user_permissions": str(pattern.get("manages_user_permissions", False)),
        "vendor_rating":        decision.get("vendor_rating", ""),
        "policy_severity":      decision.get("policy_severity", ""),
        "analyst_final_rating": decision.get("analyst_final_rating", ""),
        "override_direction":   decision.get("override_direction", ""),
        "rationale":            decision.get("rationale", ""),
        "compensating_controls_json": json.dumps(decision.get("compensating_controls", [])),
    }


def index(reset: bool = False) -> int:
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            print(f"Dropped existing collection '{COLLECTION_NAME}'.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    decision_files = sorted(Path(DECISIONS_DIR).glob("*.json"))
    if not decision_files:
        print(f"No decision files found in {DECISIONS_DIR}", file=sys.stderr)
        return 0

    docs, metadatas, ids = [], [], []

    for decision_file in decision_files:
        with open(decision_file, encoding="utf-8") as fh:
            batch = json.load(fh)

        for decision in batch.get("decisions", []):
            doc_id = f"{batch['batch_id']}::{decision['decision_id']}"

            if not reset and collection.get(ids=[doc_id])["ids"]:
                continue

            docs.append(decision_to_text(decision, batch))
            metadatas.append(build_metadata(decision, batch))
            ids.append(doc_id)

    if not docs:
        existing = collection.count()
        print(f"Nothing new to index. Collection already contains {existing} decisions.")
        return existing

    collection.add(documents=docs, metadatas=metadatas, ids=ids)

    total = collection.count()
    print(
        f"Indexed {len(docs)} decisions from {len(decision_files)} files. "
        f"Collection total: {total}."
    )
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index PAA analyst decisions into ChromaDB.")
    parser.add_argument("--reset", action="store_true", help="Drop and rebuild the collection.")
    args = parser.parse_args()
    index(reset=args.reset)
