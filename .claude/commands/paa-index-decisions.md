# /paa-index-decisions

Set up or refresh the RAG vector store for the Historical Context Analyst Agent.
Embeds all analyst decisions from `historical-context-analyst/decisions/` into ChromaDB
so the agent can retrieve similar past decisions semantically at analysis time.

## Arguments
- `--reset` — Drop and fully rebuild the collection (use after editing existing decision records)

## Steps

Run the following steps in order. Stop and report clearly if any step fails.

All bash commands must run from the **project root**. Determine it with:
```bash
git rev-parse --show-toplevel
```

### 1. Verify Python is available

```bash
cd "$(git rev-parse --show-toplevel)" && python --version
```

If Python is not found, try `python3 --version`. Report the version found.
If neither is available, stop and tell the user to install Python 3.9+.

### 2. Install RAG dependencies

```bash
cd "$(git rev-parse --show-toplevel)" && pip install -r historical-context-analyst/rag/requirements.txt --quiet
```

If this fails, report the exact pip error and stop.

### 3. Check for existing decision files

```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import pathlib, json
files = sorted(pathlib.Path('historical-context-analyst/decisions').glob('*.json'))
print(f'Found {len(files)} decision file(s):')
total = 0
for f in files:
    data = json.loads(f.read_text(encoding='utf-8'))
    n = len(data.get('decisions', []))
    total += n
    print(f'  - {f.name}: {n} decision(s)')
print(f'Total decisions: {total}')
"
```

If zero files are found, stop and tell the user to add decision files to
`historical-context-analyst/decisions/` first (or run `/paa-record-decision` to create some).

### 4. Run the indexer

If `--reset` was passed:
```bash
cd "$(git rev-parse --show-toplevel)" && python historical-context-analyst/rag/indexer.py --reset
```

Otherwise:
```bash
cd "$(git rev-parse --show-toplevel)" && python historical-context-analyst/rag/indexer.py
```

Capture and display the output.

### 5. Verify the vector store

```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import chromadb, sys
sys.path.insert(0, 'historical-context-analyst/rag')
from config import VECTOR_STORE_DIR, COLLECTION_NAME
client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
col = client.get_collection(COLLECTION_NAME)
count = col.count()
print(f'Collection \"{COLLECTION_NAME}\" contains {count} decision embeddings.')
print('Decision store is ready.' if count > 0 else 'WARNING: collection is empty.')
"
```

### 6. Run a smoke-test retrieval

```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import json, subprocess, sys
test_permission = {
    'id': 'smoke-test',
    'source_type': 'aws_iam',
    'actions': ['s3:PutBucketPolicy'],
    'action_type': {'write': True, 'manage_permissions': True, 'storage': True},
    'scope_level': 'resource',
    'principal_type': 'role',
    'effect': 'allow',
    'manages_user_permissions': True,
    'risk_rating_by_vendor': 'HIGH'
}
result = subprocess.run(
    ['python', 'historical-context-analyst/rag/retriever.py', '--top-k', '3'],
    input=json.dumps(test_permission),
    capture_output=True, text=True
)
if result.returncode != 0:
    print('Retriever error:', result.stderr)
    sys.exit(1)
data = json.loads(result.stdout)
print(f'Smoke test passed. Retrieved {data[\"decisions_returned\"]} past decision(s) for s3:PutBucketPolicy:')
for d in data['matched_decisions']:
    print(f'  [{d[\"similarity_score\"]:.2f}] {d[\"decision_id\"]} — analyst {d[\"analyst\"]} rated {d[\"analyst_final_rating\"]} ({d[\"override_direction\"]})')
    print(f'         Rationale: {d[\"rationale\"][:100]}...')
"
```

## Report

After all steps complete, summarise:
- Number of decision files indexed
- Total decisions in the vector store
- Top decisions returned in the smoke test
- Whether `--reset` was used
- Next step: tell the user they can now run PAA analysis and the Historical Context Analyst
  will surface precedents for each permission
