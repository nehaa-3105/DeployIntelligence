"""Quick smoke-test for the running API. Run after starting uvicorn."""
import urllib.request, json, sys

BASE = "http://localhost:8000"

def get(path):
    return json.loads(urllib.request.urlopen(f"{BASE}{path}").read())

def post(path, body):
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    return json.loads(urllib.request.urlopen(req).read())

# 1. Health
h = get("/health")
assert h["status"] == "ok", f"health fail: {h}"
print("HEALTH OK:", h)

# 2. Analyze — #297 demo deployment
resp = post("/analyze", {
    "deployment_id": "297",
    "service": "payment-service",
    "migration_type": "schema",
    "connection_pool_change": True,
    "change_type": "infra",
    "dependencies_changed": True,
})

print("\n=== BASELINE ===")
b = resp["baseline"]
print("  risk_level    :", b["risk_level"])
print("  cited_ids     :", b["cited_deployment_ids"])
print("  reasoning[:100]:", b["reasoning"][:100])
print("  recommendation[:80]:", b["recommendation"][:80])
assert b["risk_level"] == "high", f"Expected high, got {b['risk_level']}"
assert b["cited_deployment_ids"] == [], "Baseline should have no cited IDs"

print("\n=== MEMORY-INFORMED ===")
m = resp["memory_informed"]
print("  risk_level    :", m["risk_level"])
print("  cited_ids     :", m["cited_deployment_ids"])
hist = m["historical_deployments"]
print("  historical dep ids:", [d["deployment_id"] for d in hist])
print("  reasoning[:200]:", m["reasoning"][:200])
assert "184" in m["cited_deployment_ids"], "#184 must be cited in memory-informed"
assert any(d["deployment_id"] == "184" for d in hist), "#184 must appear in historical_deployments"
d184 = next(d for d in hist if d["deployment_id"] == "184")
assert d184["outcome"] == "incident", "#184 outcome should be incident"
assert d184["similarity_score"] == 5, f"#184 should score 5/5, got {d184['similarity_score']}"

# 3. Feedback (may return 503 if Hindsight keys not configured — that's expected)
import urllib.error
try:
    fb = post("/feedback", {
        "deployment_id": "297",
        "outcome": "success",
        "service": "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
    })
    print("\n=== FEEDBACK ===")
    print("  status :", fb["status"])
    print("  message:", fb["message"])
    assert fb["status"] == "ok", f"feedback fail: {fb}"
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    if e.code == 503:
        print("\n=== FEEDBACK ===")
        print(f"  503 Service Unavailable (Hindsight not configured): {body['detail'][:80]}")
        print("  This is expected when HINDSIGHT_API_KEY is not set in .env")
    else:
        raise

print("\nALL SMOKE TESTS PASSED")
sys.exit(0)
