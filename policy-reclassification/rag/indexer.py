"""
Indexer for the PAA Policy-Driven Reclassification RAG pipeline.

Reads every JSON file in policy-reclassification/policies/, converts each
rule into a searchable text chunk, generates sentence embeddings, and
persists them in a ChromaDB collection.

Usage (from project root):
    python policy-reclassification/rag/indexer.py
    python policy-reclassification/rag/indexer.py --reset   # force re-index
"""
import argparse
import json
import sys
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).parent))
from config import POLICIES_DIR, VECTOR_STORE_DIR, COLLECTION_NAME, EMBEDDING_MODEL


def rule_to_text(rule: dict, policy: dict) -> str:
    """
    Serialise a policy rule into a dense natural-language chunk for embedding.
    Includes every field that is semantically meaningful for retrieval.
    """
    triggers = rule.get("triggers", {})
    trigger_parts = []
    for k, v in triggers.items():
        if isinstance(v, list):
            trigger_parts.append(f"{k}: {', '.join(str(i) for i in v)}")
        elif isinstance(v, bool):
            if v:
                trigger_parts.append(k.replace("_", " "))
        elif v is not None:
            trigger_parts.append(f"{k}: {v}")
    trigger_text = "; ".join(trigger_parts)

    control_ref = (
        rule.get("control_ref")
        or rule.get("nist_requirement")
        or rule.get("csa_control")
        or rule.get("nist_reference")
        or ""
    )

    return (
        f"Policy: {policy.get('policy_name', '')}. "
        f"Standard: {policy.get('standard', '')}. "
        f"Rule {rule.get('rule_id', '')}: {rule.get('name', '')}. "
        f"Control: {control_ref}. "
        f"Classification: {rule.get('classification', '')}. "
        f"Severity: {rule.get('severity', '')}. "
        f"Description: {rule.get('description', '')} "
        f"Triggers: {trigger_text}. "
        f"Rationale: {rule.get('rationale', '')} "
        f"Remediation: {rule.get('remediation', '')}"
    )


def build_metadata(rule: dict, policy: dict, source_file: str) -> dict:
    """
    Flatten all fields the retriever needs into a ChromaDB-compatible
    metadata dict (string values only — ChromaDB does not support nested objects).
    """
    control_ref = (
        rule.get("control_ref")
        or rule.get("nist_requirement")
        or rule.get("csa_control")
        or rule.get("nist_reference")
        or ""
    )
    return {
        "policy_id":             policy.get("policy_id", ""),
        "policy_name":           policy.get("policy_name", ""),
        "standard":              policy.get("standard", ""),
        "source_file":           source_file,
        "rule_id":               rule.get("rule_id", ""),
        "rule_name":             rule.get("name", ""),
        "classification":        rule.get("classification", ""),
        "severity":              rule.get("severity", "LOW"),
        "control_ref":           control_ref,
        "rationale":             rule.get("rationale", ""),
        "remediation":           rule.get("remediation", ""),
        "compensating_controls": json.dumps(rule.get("compensating_controls", [])),
        "triggers_json":         json.dumps(rule.get("triggers", {})),
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

    # get_or_create so repeated runs without --reset are idempotent
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    policy_files = sorted(Path(POLICIES_DIR).glob("*.json"))
    if not policy_files:
        print(f"No policy files found in {POLICIES_DIR}", file=sys.stderr)
        return 0

    docs, metadatas, ids = [], [], []

    for policy_file in policy_files:
        with open(policy_file, encoding="utf-8") as fh:
            policy = json.load(fh)

        for rule in policy.get("rules", []):
            doc_id = f"{policy['policy_id']}::{rule['rule_id']}"

            # Skip if already indexed and reset not requested
            if not reset and collection.get(ids=[doc_id])["ids"]:
                continue

            docs.append(rule_to_text(rule, policy))
            metadatas.append(build_metadata(rule, policy, str(policy_file)))
            ids.append(doc_id)

    if not docs:
        existing = collection.count()
        print(f"Nothing new to index. Collection already contains {existing} rules.")
        return existing

    # ChromaDB embedding_function handles batching internally
    collection.add(documents=docs, metadatas=metadatas, ids=ids)

    total = collection.count()
    print(
        f"Indexed {len(docs)} rules from {len(policy_files)} policy files. "
        f"Collection total: {total}."
    )
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index PAA policy rules into ChromaDB.")
    parser.add_argument("--reset", action="store_true", help="Drop and rebuild the collection.")
    args = parser.parse_args()
    index(reset=args.reset)
