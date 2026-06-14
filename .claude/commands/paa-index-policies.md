# /paa-index-policies

Set up or refresh the RAG vector store for the Policy-Driven Reclassification Agent.
Embeds all rules from `policy-reclassification/policies/` into ChromaDB so the
reclassification agent can retrieve relevant rules semantically at analysis time.

## Arguments
- `--reset` — Drop and fully rebuild the collection (use after editing or adding policy files)

## Steps

Run the following steps in order. Stop and report clearly if any step fails.

All bash commands must be run from the **project root** (the directory containing
`policy-reclassification/`). Determine it once with:

```bash
git rev-parse --show-toplevel
```

Use that path as the working directory for every subsequent command by prepending
`cd "<project_root>" &&` to each bash call.

### 1. Verify Python is available

```bash
cd "$(git rev-parse --show-toplevel)" && python --version
```

If Python is not found, try `python3 --version`. Report the version found.
If neither is available, stop and tell the user to install Python 3.9+.

### 2. Install RAG dependencies

```bash
cd "$(git rev-parse --show-toplevel)" && pip install -r policy-reclassification/rag/requirements.txt --quiet
```

If this fails, report the exact pip error and stop. Do not proceed without dependencies.

### 3. Check for existing policy files

```bash
cd "$(git rev-parse --show-toplevel)" && python -c "import pathlib; files = list(pathlib.Path('policy-reclassification/policies').glob('*.json')); print(f'Found {len(files)} policy files:'); [print(f'  - {f.name}') for f in sorted(files)]"
```

List the files found. If zero files are found, stop and tell the user to add policy files to `policy-reclassification/policies/` first.

### 4. Run the indexer

If `--reset` was passed as an argument:
```bash
cd "$(git rev-parse --show-toplevel)" && python policy-reclassification/rag/indexer.py --reset
```

Otherwise:
```bash
cd "$(git rev-parse --show-toplevel)" && python policy-reclassification/rag/indexer.py
```

Capture and display the output. The indexer prints how many rules were indexed and the collection total.

### 5. Verify the vector store

```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import chromadb, sys
sys.path.insert(0, 'policy-reclassification/rag')
from config import VECTOR_STORE_DIR, COLLECTION_NAME
client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
col = client.get_collection(COLLECTION_NAME)
count = col.count()
print(f'Collection \"{COLLECTION_NAME}\" contains {count} rule embeddings.')
print('Vector store is ready.' if count > 0 else 'WARNING: collection is empty.')
"
```

### 6. Run a smoke-test retrieval

```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import json, subprocess, sys
test_permission = {
    'id': 'smoke-test',
    'actions': ['s3:PutBucketPolicy'],
    'action_type': {'write': True, 'manage_permissions': True, 'storage': True},
    'scope_level': 'resource',
    'principal_type': 'role',
    'effect': 'allow',
    'manages_user_permissions': True
}
result = subprocess.run(
    ['python', 'policy-reclassification/rag/retriever.py', '--top-k', '3'],
    input=json.dumps(test_permission),
    capture_output=True, text=True
)
if result.returncode != 0:
    print('Retriever error:', result.stderr)
    sys.exit(1)
data = json.loads(result.stdout)
print(f'Smoke test passed. Retrieved {data[\"rules_returned\"]} rules for a PutBucketPolicy permission:')
for r in data['retrieved_rules']:
    print(f'  [{r[\"similarity_score\"]:.2f}] {r[\"rule_id\"]} — {r[\"rule_name\"]} ({r[\"severity\"]})')
"
```

## Report

After all steps complete, summarise:
- Number of policy files indexed
- Total rules in the vector store
- Top 3 rules returned in the smoke test (rule ID, name, similarity score)
- Whether `--reset` was used
- Next step: tell the user they can now invoke the PAA Orchestrator agent to run a full permissions analysis
