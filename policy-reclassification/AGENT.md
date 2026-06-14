# Policy-Driven Reclassification Agent

**Role**: Evaluate a permissions snapshot against policy rules and classify each entry.

**Responsibilities**:
- Load policy rules from provided file paths or fall back to built-in least-privilege ruleset
- Test every collected permission against every applicable rule
- Classify each permission as compliant, over_privileged, under_privileged, or policy_violation
- Produce a prioritised remediation plan

**Output directory**: `findings/`

## Built-in rules (applied when no external policy is provided)

| Rule | Condition | Severity |
|------|-----------|----------|
| R001 | Wildcard resource with allow | HIGH |
| R002 | Wildcard action | HIGH |
| R003 | Admin/root/FullAccess privilege | CRITICAL |
| R004 | Cross-account/cross-org access | MEDIUM |
| R005 | Service account with user-level actions | MEDIUM |
| R006 | Sensitive resource missing explicit deny | LOW |
| R007 | Duplicate grants | LOW |

## Policy file formats supported

- JSON (AWS IAM policy format)
- YAML (Kubernetes RBAC, OPA Rego stubs)
- Plain text rule files (one rule per line)
- Terraform `.tf` files (resource blocks parsed for IAM)

## Findings naming convention

`findings/<scope-slug>-<YYYY-MM-DDTHHmmss>.json`
