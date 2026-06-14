"""
RAG configuration for the Historical Context Analyst Agent.
All paths are relative to the project root (PAA-Claude-MultiAgent/).
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DECISIONS_DIR     = PROJECT_ROOT / "historical-context-analyst" / "decisions"
VECTOR_STORE_DIR  = str(PROJECT_ROOT / "historical-context-analyst" / "vector_store")
COLLECTION_NAME   = "paa_analyst_decisions"

EMBEDDING_MODEL   = "all-MiniLM-L6-v2"

TOP_K             = 5
SIMILARITY_THRESHOLD = 0.30
