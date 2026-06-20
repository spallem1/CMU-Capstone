#!/usr/bin/env python3
"""
PAA HTML Report Generator

Reads one or more reclassification findings JSON files and produces a
self-contained HTML report that can be opened in any browser.

Usage:
    python paa-orchestrator/html_report.py --findings <path> [<path> ...]
    python paa-orchestrator/html_report.py --findings <path> --output <report.html>
    python paa-orchestrator/html_report.py --latest          # uses newest findings file
"""

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FINDINGS_DIR = PROJECT_ROOT / "policy-reclassification" / "findings"
REPORTS_DIR  = PROJECT_ROOT / "paa-orchestrator" / "reports"

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

def severity_rank(s):
    try:
        return SEVERITY_ORDER.index(str(s).upper())
    except (ValueError, AttributeError):
        return len(SEVERITY_ORDER)

def sev_class(s):
    return {
        "CRITICAL": "sev-critical",
        "HIGH":     "sev-high",
        "MEDIUM":   "sev-medium",
        "LOW":      "sev-low",
        "INFO":     "sev-info",
        "UNRATED":  "sev-unrated",
    }.get(str(s).upper(), "sev-info")

def cls_class(c):
    return {
        "policy_violation": "cls-violation",
        "over_privileged":  "cls-privileged",
        "compliant":        "cls-compliant",
    }.get(c, "cls-compliant")

def dir_icon(d):
    return {"upgraded": "↑", "downgraded": "↓", "unchanged": "→"}.get(d, "→")

def dir_class(d):
    return {"upgraded": "dir-up", "downgraded": "dir-down", "unchanged": "dir-same"}.get(d, "dir-same")

def badge(text, css_class):
    return f'<span class="badge {css_class}">{text}</span>'

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

STYLES = """
:root {
  --critical: #dc2626; --high: #ea580c; --medium: #ca8a04;
  --low: #2563eb;      --info: #64748b; --compliant-c: #16a34a;
  --bg: #f1f5f9; --surface: #ffffff; --border: #e2e8f0;
  --text: #1e293b;     --muted: #64748b; --header-bg: #0f172a;
  --radius: 10px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.6; }

/* ── Header ── */
header { background: var(--header-bg); color: #fff; padding: 28px 48px; }
header h1 { font-size: 22px; font-weight: 700; letter-spacing: -.4px; }
header h1 span { opacity: .45; font-weight: 400; font-size: 16px; margin-left: 10px; }
.meta { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 24px; font-size: 13px; opacity: .65; }
.meta strong { color: #fff; }

/* ── Layout ── */
main { max-width: 1200px; margin: 0 auto; padding: 36px 48px; }
section { margin-bottom: 44px; }
h2 { font-size: 17px; font-weight: 600; border-bottom: 2px solid var(--border);
     padding-bottom: 10px; margin-bottom: 20px; }
h2 .subtitle { font-size: 13px; font-weight: 400; color: var(--muted); margin-left: 8px; }

/* ── Summary cards ── */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
         gap: 16px; margin-bottom: 40px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
        padding: 20px 22px; }
.card .label { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--muted); }
.card .value { font-size: 34px; font-weight: 700; margin-top: 4px; line-height: 1; }
.c-critical .value { color: var(--critical); }
.c-high     .value { color: var(--high); }
.c-medium   .value { color: var(--medium); }
.c-up       .value { color: var(--critical); }
.c-ok       .value { color: var(--compliant-c); }

/* ── Badges ── */
.badge { display: inline-block; padding: 2px 8px; border-radius: 5px;
         font-size: 11px; font-weight: 600; letter-spacing: .3px; white-space: nowrap; }
.sev-critical { background:#fef2f2; color:var(--critical); border:1px solid #fecaca; }
.sev-high     { background:#fff7ed; color:var(--high);     border:1px solid #fed7aa; }
.sev-medium   { background:#fefce8; color:var(--medium);   border:1px solid #fef08a; }
.sev-low      { background:#eff6ff; color:var(--low);      border:1px solid #bfdbfe; }
.sev-info     { background:#f8fafc; color:var(--info);     border:1px solid #e2e8f0; }
.sev-unrated  { background:#f8fafc; color:#94a3b8; border:1px dashed #cbd5e1; font-style:italic; }
.conf-high   { background:#f0fdf4; color:var(--compliant-c); border:1px solid #bbf7d0; }
.conf-medium { background:#fefce8; color:var(--medium);      border:1px solid #fef08a; }
.conf-low    { background:#fef2f2; color:var(--critical);    border:1px solid #fecaca; }
.gaps-section { border-top: 3px solid var(--medium); padding-top: 24px; margin-top: 8px; }
.cls-violation  { background:#fef2f2; color:var(--critical); border:1px solid #fecaca; }
.cls-privileged { background:#fff7ed; color:var(--high);     border:1px solid #fed7aa; }
.cls-compliant  { background:#f0fdf4; color:var(--compliant-c); border:1px solid #bbf7d0; }
.dir-up   { background:#fef2f2; color:var(--critical); border:1px solid #fecaca; }
.dir-down { background:#f0fdf4; color:var(--compliant-c); border:1px solid #bbf7d0; }
.dir-same { background:#f8fafc; color:var(--info); border:1px solid #e2e8f0; }

/* ── Tables ── */
.tbl-wrap { overflow-x: auto; border-radius: var(--radius); border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; background: var(--surface); }
th { background: #f8fafc; text-align: left; padding: 10px 14px;
     font-size: 11px; font-weight: 600; text-transform: uppercase;
     letter-spacing: .5px; color: var(--muted); border-bottom: 1px solid var(--border); }
td { padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: #f8fafc; }

/* ── Finding cards ── */
.findings-toolbar { display: flex; gap: 8px; margin-bottom: 16px; }
.btn { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
       padding: 5px 14px; font-size: 12px; font-weight: 500; cursor: pointer;
       color: var(--text); }
.btn:hover { background: #f8fafc; }

.finding { background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius); margin-bottom: 12px; overflow: hidden; }
.finding[open] { border-color: #cbd5e1; }
.finding summary { list-style: none; cursor: pointer; padding: 16px 20px;
                   display: flex; align-items: flex-start; gap: 14px; }
.finding summary::-webkit-details-marker { display: none; }
.finding-chevron { color: var(--muted); font-size: 12px; margin-top: 2px;
                   transition: transform .15s; flex-shrink: 0; }
.finding[open] .finding-chevron { transform: rotate(90deg); }
.finding-meta { flex: 1; min-width: 0; }
.finding-id { font-family: ui-monospace, "SFMono-Regular", monospace;
              font-size: 11px; color: var(--muted); }
.finding-actions { font-size: 14px; font-weight: 600; margin-top: 2px;
                   word-break: break-all; }
.finding-badges { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
.finding-body { padding: 18px 20px; border-top: 1px solid var(--border); background: #fbfcfd; }

/* border-left by severity */
.finding.sev-critical { border-left: 4px solid var(--critical); }
.finding.sev-high     { border-left: 4px solid var(--high); }
.finding.sev-medium   { border-left: 4px solid var(--medium); }
.finding.sev-low      { border-left: 4px solid var(--low); }
.finding.sev-info     { border-left: 4px solid var(--info); }

/* detail grid inside body */
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.detail-label { font-size: 11px; text-transform: uppercase; letter-spacing: .5px;
                color: var(--muted); margin-bottom: 3px; }
.detail-value { font-size: 13px; }
code { font-family: ui-monospace, "SFMono-Regular", monospace; font-size: 12px;
       background: #f1f5f9; padding: 1px 5px; border-radius: 4px; word-break: break-all; }

.rules-list { margin-top: 14px; }
.rules-list h4 { font-size: 12px; font-weight: 600; text-transform: uppercase;
                 letter-spacing: .5px; color: var(--muted); margin-bottom: 8px; }
.rule-row { display: flex; align-items: center; gap: 8px; padding: 7px 0;
            border-bottom: 1px solid var(--border); font-size: 12px; flex-wrap: wrap; }
.rule-row:last-child { border-bottom: none; }
.sim-score { font-family: ui-monospace, monospace; font-size: 11px; color: var(--muted);
             min-width: 36px; }
.rule-std { margin-left: auto; font-size: 11px; color: var(--muted); }

.callout { margin-top: 14px; padding: 12px 14px; border-radius: 0 8px 8px 0;
           font-size: 13px; line-height: 1.5; }
.callout-why  { background: #fffbeb; border-left: 3px solid var(--medium); }
.callout-fix  { background: #f0fdf4; border-left: 3px solid var(--compliant-c); }
.callout strong { display: block; font-size: 11px; text-transform: uppercase;
                  letter-spacing: .5px; margin-bottom: 4px; color: var(--muted); }

/* ── Effort ── */
.effort-low    { color: var(--compliant-c); font-weight: 600; }
.effort-medium { color: var(--medium);      font-weight: 600; }
.effort-high   { color: var(--critical);    font-weight: 600; }

/* ── Notice ── */
.notice { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px;
          padding: 12px 16px; margin-bottom: 28px; font-size: 13px; }

/* ── Footer ── */
footer { background: var(--header-bg); color: rgba(255,255,255,.45);
         text-align: center; font-size: 12px; padding: 18px; margin-top: 20px; }

@media print {
  .finding .finding-body { display: block !important; }
  .findings-toolbar { display: none; }
  .cards { grid-template-columns: repeat(5, 1fr); }
}
"""

JS = """
function toggleAll(open) {
  document.querySelectorAll('.finding').forEach(d => d.open = open);
}
"""

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def render_finding(f, idx):
    reclass   = f.get("reclassification", {})
    vendor    = reclass.get("vendor_rating", "INFO")
    policy    = reclass.get("policy_severity", f.get("severity", "INFO"))
    direction = reclass.get("direction", "unchanged")
    cls       = f.get("classification", "compliant")
    triggered = f.get("triggered_rules", [])

    badges = " ".join([
        badge(cls.replace("_", " "), cls_class(cls)),
        badge(f"Policy: {policy}", sev_class(policy)),
        badge(f"Vendor: {vendor}", sev_class(vendor)),
        badge(f"{dir_icon(direction)} {direction}", f"badge {dir_class(direction)}") if reclass.get("delta") else "",
    ])

    # Triggered rules table
    rules_html = ""
    if triggered:
        rows = ""
        for r in sorted(triggered, key=lambda x: -x.get("similarity_score", 0)):
            score = r.get("similarity_score", 0)
            rows += f"""
            <div class="rule-row">
              <span class="sim-score">{score:.2f}</span>
              {badge(r.get("severity","?"), sev_class(r.get("severity","INFO")))}
              <strong>{r.get("rule_id","?")}</strong>
              <span style="color:var(--muted)">—</span>
              <span>{r.get("rule_name","")}</span>
              <span class="rule-std">{r.get("standard","")}</span>
            </div>"""
        rules_html = f"""
        <div class="rules-list">
          <h4>Triggered policy rules</h4>
          {rows}
        </div>"""

    justification = f.get("justification", "")
    recommendation = f.get("recommendation", "")
    compensating = f.get("compensating_controls", [])
    actions_str = ", ".join(f.get("actions", []))
    principal = f.get("principal", "*")
    resource  = f.get("resource", "*")

    body = f"""
    <div class="detail-grid">
      <div>
        <div class="detail-label">Principal</div>
        <div class="detail-value"><code>{principal}</code></div>
      </div>
      <div>
        <div class="detail-label">Resource</div>
        <div class="detail-value"><code>{resource}</code></div>
      </div>
      <div>
        <div class="detail-label">Vendor rating</div>
        <div class="detail-value">{badge(vendor, sev_class(vendor))}</div>
      </div>
      <div>
        <div class="detail-label">Policy severity</div>
        <div class="detail-value">
          {badge(policy, sev_class(policy))}
          &nbsp;{badge(f"{dir_icon(direction)} {direction}", dir_class(direction))}
        </div>
      </div>
    </div>
    {rules_html}
    """

    if justification:
        body += f"""
    <div class="callout callout-why">
      <strong>Why this applies</strong>
      {justification}
    </div>"""

    if recommendation or compensating:
        comp_html = ""
        if compensating:
            comp_html = "<br><br><strong>Compensating controls</strong> " + " &middot; ".join(compensating)
        body += f"""
    <div class="callout callout-fix">
      <strong>Recommendation</strong>
      {recommendation}{comp_html}
    </div>"""

    severity_for_border = sev_class(policy)
    is_open = "open" if idx < 3 else ""

    return f"""
  <details class="finding {severity_for_border}" {is_open}>
    <summary>
      <span class="finding-chevron">&#9656;</span>
      <div class="finding-meta">
        <div class="finding-id">{f.get("permission_id","?")}</div>
        <div class="finding-actions">{actions_str}</div>
        <div class="finding-badges">{badges}</div>
      </div>
    </summary>
    <div class="finding-body">{body}</div>
  </details>"""


def render_remediation(plan):
    if not plan:
        return "<p style='color:var(--muted)'>No remediation plan in findings.</p>"
    effort_cls = {"low": "effort-low", "medium": "effort-medium", "high": "effort-high"}
    rows = ""
    for item in plan:
        effort = str(item.get("estimated_effort", "medium")).lower()
        affected = ", ".join(item.get("affected_permission_ids", []))
        standards = " &middot; ".join(item.get("standard_refs", []))
        rows += f"""<tr>
          <td><strong>#{item.get("priority","?")}</strong></td>
          <td>{item.get("action","")}</td>
          <td><code style="font-size:11px">{affected}</code></td>
          <td style="font-size:12px;color:var(--muted)">{standards}</td>
          <td class="{effort_cls.get(effort,'effort-medium')}">{effort}</td>
        </tr>"""
    return f"""
  <div class="tbl-wrap"><table>
    <thead><tr><th>#</th><th>Action</th><th>Permissions</th><th>Standards</th><th>Effort</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>"""


def conf_class(score) -> str:
    try:
        v = float(score)
    except (TypeError, ValueError):
        return "conf-low"
    if v >= 0.85:
        return "conf-high"
    if v >= 0.75:
        return "conf-medium"
    return "conf-low"


def render_low_confidence(skipped: list) -> str:
    if not skipped:
        return ""
    rows = ""
    for e in skipped:
        score = e.get("normalization_confidence", e.get("normalization_score", 0))
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            score_f = 0.0
        notes = "; ".join(e.get("normalization_notes", []))
        actions_str = ", ".join(e.get("actions", []))
        rows += f"""<tr>
          <td><code>{e.get("permission_id", "?")}</code></td>
          <td><code>{e.get("scope_name", actions_str or "?")}</code></td>
          <td>{badge(f"{score_f:.2f}", conf_class(score_f))}</td>
          <td style="font-size:12px;color:var(--muted)">{notes or e.get("reason","")}</td>
        </tr>"""
    return f"""
<section class="gaps-section">
  <h2>Errors &amp; Gaps <span class="subtitle">({len(skipped)} permission(s) excluded from policy analysis)</span></h2>
  <div class="notice" style="margin-bottom:16px">
    <strong>Low normalization confidence:</strong> The entries below were excluded from the
    RAG policy pipeline because the Permission Collector's self-evaluation scored them below
    P(True)&nbsp;=&nbsp;0.75. Feeding ambiguous normalizations into the retriever produces
    confidently wrong findings. Recommend re-collecting these permissions from more granular
    source documentation.
  </div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>ID</th><th>Scope / Action</th><th>Score</th><th>Reason</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</section>"""


def render_compliant_table(findings):
    rows_data = [f for f in findings if f.get("classification") == "compliant"]
    if not rows_data:
        return "<p style='color:var(--muted)'>No permissions classified as fully compliant.</p>"
    rows = ""
    for f in rows_data:
        vendor = f.get("reclassification", {}).get("vendor_rating", "INFO")
        rows += f"""<tr>
          <td><code>{f.get("permission_id","?")}</code></td>
          <td>{", ".join(f.get("actions",[]))}</td>
          <td><code>{f.get("principal","*")}</code></td>
          <td><code>{f.get("resource","*")}</code></td>
          <td>{badge(vendor, sev_class(vendor))}</td>
        </tr>"""
    return f"""
  <div class="tbl-wrap"><table>
    <thead><tr><th>ID</th><th>Actions</th><th>Principal</th><th>Resource</th><th>Vendor Rating</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>"""


# ---------------------------------------------------------------------------
# Schema normalisation — convert different agent output formats to canonical
# ---------------------------------------------------------------------------

_SENS_TO_SEV = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}
_SEV_RANK    = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# Minimum policy severity floor by raw (agent-side) classification
_CLS_SEV_FLOOR = {
    "privileged_and_risky": "HIGH",
    "privileged": "HIGH",
    "risky": "MEDIUM",
    "compliant": "INFO",
}

_CLS_CANONICAL = {
    "privileged_and_risky": "policy_violation",
    "privileged":           "over_privileged",
    "risky":                "policy_violation",
    "compliant":            "compliant",
}


def _policy_sev(raw_cls: str, vendor_sev: str) -> str:
    """Derive policy severity: at least the floor for the classification."""
    floor = _SEV_RANK.get(_CLS_SEV_FLOOR.get(raw_cls, "INFO"), 0)
    v     = _SEV_RANK.get(vendor_sev.upper(), 0)
    if v >= floor:
        return vendor_sev.upper()
    return _CLS_SEV_FLOOR.get(raw_cls, "INFO")


def _direction(vendor_sev: str, policy_sev: str) -> str:
    v = _SEV_RANK.get(vendor_sev.upper(), 0)
    p = _SEV_RANK.get(policy_sev.upper(), 0)
    if p > v: return "upgraded"
    if p < v: return "downgraded"
    return "unchanged"


def _normalize_github_oauth(d: dict) -> dict:
    """Normalize policy_reclassification_output (GitHub OAuth / SaaS) format."""
    inner = d.get("policy_reclassification_output", d)

    # Build severity lookup from top_violations (has explicit severity field)
    top_sev: dict[str, str] = {}
    for tv in inner.get("top_violations", []):
        top_sev[tv["scope_name"]] = tv.get("severity", "HIGH").upper()

    findings = []
    for entry in inner.get("classifications", []):
        scope_name = entry.get("scope_name", "unknown")
        vendor_sev = _SENS_TO_SEV.get(entry.get("original_sensitivity", "low").lower(), "LOW")
        raw_cls    = entry.get("classification", "compliant")
        can_cls    = _CLS_CANONICAL.get(raw_cls, "compliant")
        pol_sev    = top_sev.get(scope_name) or _policy_sev(raw_cls, vendor_sev)
        direction  = _direction(vendor_sev, pol_sev)

        triggered = [
            {"rule_id": r, "rule_name": "", "similarity_score": 0.0,
             "severity": pol_sev, "standard": ""}
            for r in entry.get("policy_rules_applied", [])
        ]

        findings.append({
            "permission_id": scope_name,
            "actions":       [scope_name],
            "principal":     "*",
            "resource":      "*",
            "classification": can_cls,
            "severity":       pol_sev,
            "reclassification": {
                "vendor_rating":   vendor_sev,
                "policy_severity": pol_sev,
                "direction":       direction,
                "delta":           direction != "unchanged",
            },
            "triggered_rules":     triggered,
            "justification":       entry.get("rationale", ""),
            "recommendation":      entry.get("recommended_action", ""),
            "compensating_controls": [],
        })

    # Severity counts from non-compliant findings
    sev_counts: dict[str, int] = {}
    dir_counts  = {"upgraded": 0, "downgraded": 0, "unchanged": 0}
    for f in findings:
        if f["classification"] != "compliant":
            sev = f["reclassification"]["policy_severity"]
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
        d2 = f["reclassification"]["direction"]
        dir_counts[d2] = dir_counts.get(d2, 0) + 1

    raw_s = inner.get("summary", {})
    n_compliant = raw_s.get("compliant", sum(1 for f in findings if f["classification"] == "compliant"))
    n_privileged = raw_s.get("privileged", 0)
    n_risky      = raw_s.get("risky", 0)
    n_both       = raw_s.get("privileged_and_risky", 0)

    return {
        "scope":        inner.get("scope", "github-oauth"),
        "analysed_at":  inner.get("analysed_at", ""),
        "rag_enabled":  True,
        "source_type":  "saas:github-oauth",
        "policy_corpus": inner.get("policy_corpus", []),
        "findings":       findings,
        "remediation_plan": [],
        "summary": {
            "total_permissions": raw_s.get("total", len(findings)),
            "compliant":         n_compliant,
            "over_privileged":   n_privileged,
            "policy_violations": n_risky + n_both,
            "critical": sev_counts.get("CRITICAL", 0),
            "high":     sev_counts.get("HIGH", 0),
            "medium":   sev_counts.get("MEDIUM", 0),
            "low":      sev_counts.get("LOW", 0),
            "reclassification": {
                "upgraded":   dir_counts["upgraded"],
                "downgraded": dir_counts["downgraded"],
                "unchanged":  dir_counts["unchanged"],
            },
        },
    }


def _normalize_aws(d: dict) -> dict:
    """Normalize AWS reclassification_version format."""
    findings = []
    for entry in d.get("findings", []):
        vendor_sev = entry.get("vendor_rating", "INFO").upper()
        pol_sev    = entry.get("reclassified_severity", vendor_sev).upper()
        raw_cls    = entry.get("policy_classification", "compliant")
        can_cls    = _CLS_CANONICAL.get(raw_cls, "compliant")
        direction  = _direction(vendor_sev, pol_sev)

        triggered = [
            {
                "rule_id":         r.get("rule_id", ""),
                "rule_name":       r.get("rule_name", ""),
                "similarity_score": r.get("similarity_score", 0.0),
                "severity":        r.get("severity", "INFO"),
                "standard":        r.get("standard", r.get("policy_id", "")),
            }
            for r in entry.get("triggered_rules", [])
        ]

        findings.append({
            "permission_id": entry.get("permission_id", ""),
            "actions":       [entry["api_operation"]] if entry.get("api_operation") else [],
            "principal":     entry.get("principal", "*"),
            "resource":      entry.get("resource", "*"),
            "classification": can_cls,
            "severity":       pol_sev,
            "reclassification": {
                "vendor_rating":   vendor_sev,
                "policy_severity": pol_sev,
                "direction":       direction,
                "delta":           direction != "unchanged",
            },
            "triggered_rules":     triggered,
            "justification":       entry.get("rationale", ""),
            "recommendation":      entry.get("recommended_action", ""),
            "compensating_controls": entry.get("compensating_controls", []),
        })

    s        = d.get("summary", {})
    total    = s.get("total_analysed", len(findings))
    upgraded = s.get("ratings_upgraded", 0)
    downgraded = s.get("ratings_downgraded", 0)

    return {
        "scope":        d.get("scope", "aws"),
        "analysed_at":  d.get("analysed_at", ""),
        "rag_enabled":  d.get("rag_enabled", True),
        "source_type":  d.get("source_type", "aws"),
        "policy_corpus": d.get("policy_corpus", []),
        "findings":       findings,
        "remediation_plan": d.get("remediation_plan", []),
        "summary": {
            "total_permissions": total,
            "compliant":         s.get("compliant", 0),
            "over_privileged":   s.get("privileged", 0) + s.get("privileged_and_risky", 0),
            "policy_violations": s.get("policy_violations", 0),
            "critical": s.get("critical", 0),
            "high":     s.get("high", 0),
            "medium":   s.get("medium", 0),
            "low":      s.get("low", 0),
            "reclassification": {
                "upgraded":   upgraded,
                "downgraded": downgraded,
                "unchanged":  max(0, total - upgraded - downgraded),
            },
        },
    }


def normalize(d: dict) -> dict:
    """Auto-detect findings schema and convert to canonical format."""
    if "policy_reclassification_output" in d:
        return _normalize_github_oauth(d)
    if "reclassification_version" in d or "agent" in d:
        return _normalize_aws(d)
    return d  # assume already canonical


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------

def generate(findings_data_list: list[dict], output_path: Path) -> None:
    summary = {k: 0 for k in ["total","compliant","over_privileged","policy_violations",
                               "critical","high","medium","low","upgraded","downgraded","unchanged"]}
    all_findings, all_remediation, all_low_confidence = [], [], []
    scope = None
    analysed_at = None
    rag_enabled = True
    source_types: list[str] = []
    policy_corpus: set[str] = set()

    for d in findings_data_list:
        d = normalize(d)
        scope       = scope       or d.get("scope", "unknown")
        analysed_at = analysed_at or d.get("analysed_at", "")
        if not d.get("rag_enabled", True):
            rag_enabled = False
        source_types.append(d.get("source_type", "unknown"))
        policy_corpus.update(d.get("policy_corpus", []))

        s = d.get("summary", {})
        summary["total"]            += s.get("total_permissions", 0)
        summary["compliant"]        += s.get("compliant", 0)
        summary["over_privileged"]  += s.get("over_privileged", 0)
        summary["policy_violations"]+= s.get("policy_violations", 0)
        summary["critical"]         += s.get("critical", 0)
        summary["high"]             += s.get("high", 0)
        summary["medium"]           += s.get("medium", 0)
        summary["low"]              += s.get("low", 0)
        r = s.get("reclassification", {})
        summary["upgraded"]  += r.get("upgraded", 0)
        summary["downgraded"]+= r.get("downgraded", 0)
        summary["unchanged"] += r.get("unchanged", 0)

        all_findings.extend(d.get("findings", []))
        all_remediation.extend(d.get("remediation_plan", []))
        all_low_confidence.extend(d.get("low_confidence_skipped", []))

    def sort_key(f):
        cls = f.get("classification", "compliant")
        pol = f.get("reclassification", {}).get("policy_severity", f.get("severity", "INFO"))
        direction = f.get("reclassification", {}).get("direction", "unchanged")
        cls_rank = {"policy_violation": 0, "over_privileged": 1, "compliant": 2}.get(cls, 2)
        dir_rank = {"upgraded": 0, "unchanged": 1, "downgraded": 2}.get(direction, 3)
        return (cls_rank, severity_rank(pol), dir_rank)

    all_findings.sort(key=sort_key)
    all_remediation.sort(key=lambda x: x.get("priority", 999))

    non_compliant = [f for f in all_findings if f.get("classification") != "compliant"]

    date_str = (analysed_at or datetime.now().isoformat())[:10]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    sources_html = " &middot; ".join(f"<code>{s}</code>" for s in source_types if s)
    corpus_html  = " &middot; ".join(f"<code>{p}</code>" for p in sorted(policy_corpus))

    rag_notice = "" if rag_enabled else """
  <div class="notice">
    <strong>Notice:</strong> The RAG pipeline was unavailable — findings are based on
    built-in fallback rules only. Run <code>/paa-index-policies</code> and re-analyse
    for full NIST/CSA policy coverage.
  </div>"""

    # findings section
    if non_compliant:
        findings_section = f"""
  <div class="findings-toolbar">
    <button class="btn" onclick="toggleAll(true)">Expand all</button>
    <button class="btn" onclick="toggleAll(false)">Collapse all</button>
  </div>
  {"".join(render_finding(f, i) for i, f in enumerate(non_compliant))}"""
    else:
        findings_section = "<p style='color:var(--compliant-c);font-weight:600'>All permissions are compliant. No policy violations found.</p>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PAA Report — {scope}</title>
<style>{STYLES}</style>
</head>
<body>

<header>
  <h1>PAA Permissions Analysis <span>{scope}</span></h1>
  <div class="meta">
    <span>Date: <strong>{date_str}</strong></span>
    <span>Sources: <strong>{sources_html or "—"}</strong></span>
    <span>Policy corpus: <strong>{corpus_html or "built-in rules"}</strong></span>
    <span>RAG: <strong>{"enabled" if rag_enabled else "disabled (fallback)"}</strong></span>
  </div>
</header>

<main>
{rag_notice}

<!-- ── Summary cards ── -->
<div class="cards">
  <div class="card"><div class="label">Total Permissions</div><div class="value">{summary["total"]}</div></div>
  <div class="card c-critical"><div class="label">Critical</div><div class="value">{summary["critical"]}</div></div>
  <div class="card c-high"><div class="label">High</div><div class="value">{summary["high"]}</div></div>
  <div class="card c-up"><div class="label">Upgraded by Policy</div><div class="value">{summary["upgraded"]}</div></div>
  <div class="card c-ok"><div class="label">Compliant</div><div class="value">{summary["compliant"]}</div></div>
</div>

<!-- ── Reclassification summary ── -->
<section>
  <h2>Reclassification Summary</h2>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Direction</th><th>Count</th><th>Meaning</th></tr></thead>
    <tbody>
      <tr>
        <td>{badge("↑ Upgraded", "dir-up")}</td>
        <td><strong>{summary["upgraded"]}</strong></td>
        <td>Vendor under-estimated risk — immediate analyst review needed</td>
      </tr>
      <tr>
        <td>{badge("→ Unchanged", "dir-same")}</td>
        <td><strong>{summary["unchanged"]}</strong></td>
        <td>Vendor and policy agree on severity level</td>
      </tr>
      <tr>
        <td>{badge("↓ Downgraded", "dir-down")}</td>
        <td><strong>{summary["downgraded"]}</strong></td>
        <td>Vendor was conservative — context suggests lower residual risk</td>
      </tr>
      <tr>
        <td>{badge("Compliant", "cls-compliant")}</td>
        <td><strong>{summary["compliant"]}</strong></td>
        <td>No NIST/CSA policy rules triggered at this scope</td>
      </tr>
    </tbody>
  </table></div>

  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:16px;">
    <div class="card" style="padding:14px 18px">
      <div class="label">Policy Violations</div>
      <div class="value" style="font-size:24px;color:var(--critical)">{summary["policy_violations"]}</div>
    </div>
    <div class="card" style="padding:14px 18px">
      <div class="label">Over-Privileged</div>
      <div class="value" style="font-size:24px;color:var(--high)">{summary["over_privileged"]}</div>
    </div>
    <div class="card" style="padding:14px 18px">
      <div class="label">Medium / Low</div>
      <div class="value" style="font-size:24px;color:var(--medium)">{summary["medium"] + summary["low"]}</div>
    </div>
  </div>
</section>

<!-- ── Findings ── -->
<section>
  <h2>Findings <span class="subtitle">({len(non_compliant)} non-compliant — first 3 expanded)</span></h2>
  {findings_section}
</section>

<!-- ── Remediation ── -->
<section>
  <h2>Prioritised Remediation Plan</h2>
  {render_remediation(all_remediation)}
</section>

<!-- ── Compliant ── -->
<section>
  <h2>Compliant Permissions</h2>
  {render_compliant_table(all_findings)}
</section>

{render_low_confidence(all_low_confidence)}

</main>

<footer>
  Generated by PAA (Permissions Analyser Agent) &middot; {generated_at}
</footer>

<script>{JS}</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate a PAA HTML report from findings JSON file(s)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--findings", nargs="+", metavar="PATH",
                       help="Path(s) to reclassification findings JSON file(s)")
    group.add_argument("--latest", action="store_true",
                       help="Auto-discover and use the most recently modified findings file")
    parser.add_argument("--output", metavar="PATH",
                        help="Output HTML file (default: paa-orchestrator/reports/<stem>.html)")
    args = parser.parse_args()

    if args.latest:
        candidates = sorted(FINDINGS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print(f"No findings files found in {FINDINGS_DIR}", file=sys.stderr)
            sys.exit(1)
        findings_paths = [candidates[0]]
        print(f"Using latest findings: {candidates[0]}")
    else:
        findings_paths = [Path(p) for p in args.findings]

    findings_data = []
    for fp in findings_paths:
        if not fp.exists():
            print(f"Error: not found — {fp}", file=sys.stderr)
            sys.exit(1)
        with open(fp, encoding="utf-8") as fh:
            findings_data.append(json.load(fh))

    if args.output:
        output_path = Path(args.output)
    else:
        stem = findings_paths[0].stem
        output_path = REPORTS_DIR / f"{stem}.html"

    generate(findings_data, output_path)
    print(f"HTML report written to: {output_path}")


if __name__ == "__main__":
    main()
