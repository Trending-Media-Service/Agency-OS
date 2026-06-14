import pytest
from app.kernel.services import evaluate_gates
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

def _build_op(diff: str = None) -> OpSpec:
    params = {
        "intent": "test build",
        "branch_name": "test-branch",
        "repo": "git@github.com:test/test.git"
    }
    if diff is not None:
        params["diff"] = diff
        
    return OpSpec(
        id="op_test_123",
        tenant_id="t1",
        brand_id="b1",
        domain="build",
        action="build.deliver",
        params=params,
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(amount_minor=1000, currency="INR"),
    )

# ----------------------------------------------------------- protected paths
def test_gate_protected_paths_pass_clean():
    op = _build_op(diff="")
    gate = evaluate_gates(op)
    assert not gate.blocked
    assert len(gate.violations) == 0

def test_gate_protected_paths_pass_safe_files():
    diff = """diff --git a/src/App.js b/src/App.js
index 1234567..89abcde 100644
--- a/src/App.js
+++ b/src/App.js
@@ -10,5 +10,5 @@ function App() {
-  return <Hero color="red" />;
+  return <Hero color="blue" />;
 }"""
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert not gate.blocked
    assert len(gate.violations) == 0

def test_gate_protected_paths_blocks_control_plane():
    diff = """diff --git a/control-plane/app/main.py b/control-plane/app/main.py
index 1234567..89abcde 100644
--- a/control-plane/app/main.py
+++ b/control-plane/app/main.py
@@ -1,5 +1,6 @@
+# Hacky change
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_protected_paths" for v in gate.violations)
    assert "control-plane/app/main.py" in gate.violations[0].attempted

def test_gate_protected_paths_blocks_github_workflows():
    diff = """diff --git a/.github/workflows/deploy.yml b/.github/workflows/deploy.yml
index 1234567..89abcde 100644
--- a/.github/workflows/deploy.yml
+++ b/.github/workflows/deploy.yml
@@ -1,5 +1,6 @@
+# Malicious workflow
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_protected_paths" for v in gate.violations)

def test_gate_protected_paths_blocks_owners():
    diff = """diff --git a/OWNERS b/OWNERS
index 1234567..89abcde 100644
--- a/OWNERS
+++ b/OWNERS
@@ -1,2 +1,3 @@
 chandan
+attacker
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_protected_paths" for v in gate.violations)

# ----------------------------------------------------------- dependency allowlist
def test_gate_deps_pass_no_package_json():
    diff = """diff --git a/src/App.js b/src/App.js
index 1234567..89abcde 100644
--- a/src/App.js
+++ b/src/App.js
@@ -1,1 +1,2 @@
+import React from 'react';
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert not gate.blocked

def test_gate_deps_pass_approved_deps():
    diff = """diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -12,4 +12,5 @@
   "dependencies": {
     "react": "^18.2.0",
+    "tailwindcss": "^3.3.0",
     "next": "^13.4.0"
   }
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert not gate.blocked

def test_gate_deps_blocks_unapproved_deps():
    diff = """diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -12,4 +12,5 @@
   "dependencies": {
     "react": "^18.2.0",
+    "express": "^4.18.2",
     "next": "^13.4.0"
   }
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_dependency_allowlist" for v in gate.violations)
    assert "express" in gate.violations[0].attempted

def test_gate_deps_pass_non_dep_package_json_changes():
    diff = """diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- b/package.json
+++ b/package.json
@@ -2,3 +2,3 @@
   "name": "my-app",
-  "version": "0.1.0",
+  "version": "0.2.0",
   "description": "My App Description",
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert not gate.blocked

# ----------------------------------------------------------- secret scan
def test_gate_secrets_pass_clean():
    diff = """diff --git a/src/App.js b/src/App.js
index 1234567..89abcde 100644
--- a/src/App.js
+++ b/src/App.js
@@ -1,2 +1,2 @@
-const apiKey = "mock-key-for-local-dev";
+const apiKey = process.env.API_KEY;
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert not gate.blocked

def test_gate_secrets_blocks_google_api_key():
    key_val = "AIzaSy" + "AzbCDeFGhIjKlMnOpQrStUvWxYz123456"
    diff = f"""diff --git a/src/App.js b/src/App.js
index 1234567..89abcde 100644
--- a/src/App.js
+++ b/src/App.js
@@ -1,2 +1,2 @@
-const key = null;
+const key = "{key_val}";
"""
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_secret_scan" for v in gate.violations)
    assert "Google API Key" in gate.violations[0].attempted

def test_gate_secrets_blocks_openai_key():
    diff = """diff --git a/src/App.js b/src/App.js
index 1234567..89abcde 100644
--- a/src/App.js
+++ b/src/App.js
@@ -1,2 +1,2 @@
-const key = null;
+const key = "sk-proj-1234567890abcdef1234567890abcdef12345678";
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_secret_scan" for v in gate.violations)
    assert "OpenAI Project API Key" in gate.violations[0].attempted

def test_gate_secrets_blocks_private_key():
    header = "-----BEGIN " + "PRIVATE KEY-----"
    footer = "-----END " + "PRIVATE KEY-----"
    diff = f"""diff --git a/src/App.js b/src/App.js
index 1234567..89abcde 100644
--- a/src/App.js
+++ b/src/App.js
@@ -0,0 +1,5 @@
+const key = `{header}
+MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC3
+...
+{footer}`;
"""
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_secret_scan" for v in gate.violations)
    assert "Private Key" in gate.violations[0].attempted

def test_gate_secrets_blocks_generic_secret():
    diff = """diff --git a/src/App.js b/src/App.js
index 1234567..89abcde 100644
--- a/src/App.js
+++ b/src/App.js
@@ -1,2 +1,2 @@
-let pass = null;
+let db_password = "my-super-secret-password-123";
 """
    op = _build_op(diff=diff)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert any(v.rule_id == "build_secret_scan" for v in gate.violations)
    assert "Potential hardcoded secret" in gate.violations[0].attempted
