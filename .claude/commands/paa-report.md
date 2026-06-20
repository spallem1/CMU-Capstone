# /paa-report

Generate (or regenerate) a self-contained HTML report from existing PAA findings.

Use this when:
- You want to open an analysis result in a browser without re-running the full pipeline
- The HTML file was not produced by an earlier orchestrator run
- You edited a findings JSON and want to refresh the HTML

## Arguments

- *(no argument)* — generate HTML from the most recently modified findings file
- `<scope-slug>` — generate HTML from all findings files matching `*<scope-slug>*.json`
- `--all` — generate one HTML file per findings file found in `policy-reclassification/findings/`

## Steps

Run from the **project root**. Determine it once with:

```bash
git rev-parse --show-toplevel
```

### 1. Verify Python is available

```bash
cd "$(git rev-parse --show-toplevel)" && python --version
```

If Python is not found, try `python3`. Report the version.
If neither works, stop and tell the user to install Python 3.9+.

### 2. Locate findings files

**No argument or `--all`:**
```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import pathlib, json
files = sorted(pathlib.Path('policy-reclassification/findings').glob('*.json'),
               key=lambda p: p.stat().st_mtime, reverse=True)
for f in files:
    data = json.loads(f.read_text(encoding='utf-8'))
    total = data.get('summary', {}).get('total_permissions', '?')
    at = data.get('analysed_at', '')[:10]
    print(f'{f.name}  |  {total} permissions  |  {at}')
print(f'Total: {len(files)} findings file(s)')
"
```

List the files found and their metadata. If zero files are found, stop and tell the
user to run a PAA analysis first (via the PAA Orchestrator agent).

**With `<scope-slug>`:**
```bash
cd "$(git rev-parse --show-toplevel)" && python -c "
import pathlib
slug = '<scope-slug>'
files = list(pathlib.Path('policy-reclassification/findings').glob(f'*{slug}*.json'))
for f in sorted(files): print(f)
"
```

### 3. Generate HTML

**For the latest file only (no argument):**
```bash
cd "$(git rev-parse --show-toplevel)" && python paa-orchestrator/html_report.py --latest
```

**For a specific scope slug:**
```bash
cd "$(git rev-parse --show-toplevel)" && python paa-orchestrator/html_report.py \
  --findings policy-reclassification/findings/<matching-files...>
```

**For `--all`:**
Run `python paa-orchestrator/html_report.py --findings <file>` once per findings file,
so each gets its own HTML report in `paa-orchestrator/reports/`.

### 4. Report results

After generation, tell the user:
- The path to each HTML file generated
- How many permissions and findings it covers
- That they can open the file directly in any browser

If the generator fails, show the exact Python error and suggest checking that
`paa-orchestrator/html_report.py` exists and `policy-reclassification/findings/`
contains valid JSON files produced by the Policy-Driven Reclassification Agent.
