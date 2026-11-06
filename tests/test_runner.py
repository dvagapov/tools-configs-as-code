import json
from pathlib import Path

import pytest
import yaml

from cac.config import ConfigError, load_config
from cac.runner import run_workflow

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "framework" / "defaults.yaml"
PINS = load_config(DEFAULTS)["pins"]
PROBES = {**PINS, "runtime": "running"}
SCRIPT = {"plan_gate": "approved", "precommit_review": "pass", "final_review": "pass", "await_merge": "merged"}


def adapter(state):
    return SCRIPT.get(state, "ok")


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".cac").mkdir(parents=True)
    ws = tmp_path / "workspace.yaml"
    ws.write_text(yaml.safe_dump({
        "schemaVersion": 1, "workspace": "acme", "frameworkRef": "x@v1",
        "repos": [{"name": "fx", "url": "https://github.com/o/fx.git", "host": "github"}]}))
    policy = tmp_path / "repo-policy.yaml"

    def write_policy(manifest=".cac/verify.yaml"):
        policy.write_text(yaml.safe_dump({
            "schemaVersion": 1, "baseBranch": "develop", "branchPattern": "agent/{task_id}",
            "verification": {"manifest": manifest}}))

    def write_verify(code):
        (repo / ".cac" / "verify.yaml").write_text(yaml.safe_dump({
            "schemaVersion": 1, "steps": [{"id": "unit", "run": ["python3", "-c", code], "expectExit": 0}]}))

    write_policy()
    return type("E", (), dict(repo=repo, ws=ws, policy=policy, audit=tmp_path / "audit",
                              write_policy=staticmethod(write_policy), write_verify=staticmethod(write_verify)))


def go(env, probes=PROBES, run_id="r_1"):
    return run_workflow(DEFAULTS, env.ws, env.policy, env.repo, adapter, probes, env.audit, run_id)


def test_success_writes_audit_and_manifest(env):
    env.write_verify("pass")
    res = go(env)
    assert res.final == "done"
    lines = [json.loads(l) for l in (env.audit / "r_1.jsonl").read_text().splitlines()]
    assert len(lines) == len(res.events) and any(r["event"] == "step_result" for r in lines)
    m = yaml.safe_load((env.audit / "r_1.manifest.yaml").read_text())
    assert m["result"]["final"] == "done" and m["workspace"] == "acme" and len(m["configSha256"]) == 64


def test_failing_verification_ends_blocked_and_is_audited(env):
    env.write_verify("import sys; sys.exit(1)")
    res = go(env)
    assert res.final == "blocked:remediation_exhausted"
    m = yaml.safe_load((env.audit / "r_1.manifest.yaml").read_text())
    assert m["result"]["final"] == res.final


def test_missing_manifest_blocks(env):
    assert go(env).final == "blocked:no_manifest"


def test_drift_blocked_but_still_audited(env):
    env.write_verify("pass")
    res = go(env, probes={**PROBES, "claude": "0.0.1"})
    assert res.final == "blocked:drift"
    assert (env.audit / "r_1.jsonl").exists()


def test_manifest_path_escape_rejected_before_anything_runs(env):
    env.write_policy("../../etc/passwd")
    with pytest.raises(ConfigError, match="escapes"):
        go(env)
    assert not env.audit.exists()


def test_invalid_config_raises_before_audit(env):
    env.ws.write_text(yaml.safe_dump({"schemaVersion": 1}))
    with pytest.raises(ConfigError):
        go(env)
    assert not env.audit.exists()
