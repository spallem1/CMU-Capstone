"""Test all 4 MCP tools via the JSON-RPC stdio protocol."""
import json
import subprocess
import sys
from pathlib import Path

SERVER = str(Path(__file__).parent / "server.py")

proc = subprocess.Popen(
    [sys.executable, SERVER],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
)


def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def recv():
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else None


# 1. Initialize
send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2024-11-05", "capabilities": {},
    "clientInfo": {"name": "test-client", "version": "1.0"},
}})
r = recv()
print("Server:", r["result"]["serverInfo"]["name"])
print("Protocol:", r["result"]["protocolVersion"])

send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

# 2. List tools
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
r = recv()
tools = r["result"]["tools"]
print(f"\nTools ({len(tools)}):")
for t in tools:
    print(f"  {t['name']}")

# 3. paa_store_status
print("\n--- paa_store_status ---")
send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
      "params": {"name": "paa_store_status", "arguments": {}}})
r = recv()
s = json.loads(r["result"]["content"][0]["text"])
print(f"  policy_rules:      {s['policy_rules']['count']} ({s['policy_rules']['status']})")
print(f"  analyst_decisions: {s['analyst_decisions']['count']} ({s['analyst_decisions']['status']})")

# Shared test permission
perm = {
    "id": "t1", "source_type": "github",
    "actions": ["github:admin:org"],
    "action_type": {"admin": True, "manage_permissions": True},
    "scope_level": "org", "principal_type": "user", "effect": "allow",
    "resource": "*", "manages_user_permissions": True, "is_org_level": True,
    "risk_rating_by_vendor": "HIGH",
}

# 4. paa_retrieve_policy_rules
print("\n--- paa_retrieve_policy_rules ---")
send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
    "name": "paa_retrieve_policy_rules",
    "arguments": {"permission_json": json.dumps(perm), "top_k": 3},
}})
r = recv()
result = json.loads(r["result"]["content"][0]["text"])
print(f"  rules_returned: {result['rules_returned']}")
for rule in result["retrieved_rules"]:
    print(f"    [{rule['similarity_score']:.2f}] {rule['rule_id']} — {rule['rule_name']} ({rule['severity']})")

# 5. paa_retrieve_decisions
print("\n--- paa_retrieve_decisions ---")
send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
    "name": "paa_retrieve_decisions",
    "arguments": {"permission_json": json.dumps(perm), "top_k": 3},
}})
r = recv()
result = json.loads(r["result"]["content"][0]["text"])
print(f"  decisions_returned: {result['decisions_returned']}")
for d in result["matched_decisions"]:
    print(f"    [{d['similarity_score']:.2f}] {d['decision_id']} — "
          f"{d['analyst_final_rating']} ({d['override_direction']}) by {d['analyst']}")

# 6. paa_record_decision
print("\n--- paa_record_decision ---")
decision_payload = {
    "permission": perm,
    "analyst_final_rating": "CRITICAL",
    "override_direction": "confirmed",
    "rationale": "admin:org grants full org control; confirmed CRITICAL per dec-gh-001 precedent. JIT-only.",
    "analyst": "analyst@example.com",
    "vendor_rating": "HIGH",
    "policy_severity": "CRITICAL",
    "compensating_controls": ["JIT approval required", "MFA enforced", "Monthly audit-log review"],
}
send({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
    "name": "paa_record_decision",
    "arguments": {"decision_json": json.dumps(decision_payload)},
}})
r = recv()
result = json.loads(r["result"]["content"][0]["text"])
print(f"  status:           {result['status']}")
print(f"  decision_id:      {result['decision_id']}")
print(f"  decision_file:    {result['decision_file']}")
print(f"  decisions_in_batch: {result['decisions_in_batch']}")
print(f"  indexer:          {result['indexer']}")

proc.terminate()
proc.wait()
print("\nAll tools passed.")
