"""
RAG configuration for the Policy-Driven Reclassification Agent.
All paths are relative to the project root (PAA-Claude-MultiAgent/).
"""
from pathlib import Path

# Resolve project root as two levels up from this file
PROJECT_ROOT = Path(__file__).resolve().parents[2]

POLICIES_DIR      = PROJECT_ROOT / "policy-reclassification" / "policies"
VECTOR_STORE_DIR  = str(PROJECT_ROOT / "policy-reclassification" / "vector_store")
COLLECTION_NAME   = "paa_policy_rules"

# Embedding model — lightweight, runs fully offline
EMBEDDING_MODEL   = "all-MiniLM-L6-v2"

# Number of rules to retrieve per permission entry
TOP_K = 5

# Minimum cosine similarity (0–1) below which a retrieved rule is discarded
SIMILARITY_THRESHOLD = 0.25
