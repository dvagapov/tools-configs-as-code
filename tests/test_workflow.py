from pathlib import Path

import pytest

from cac.config import load_config
from cac.workflow import TRANSITIONS, run

DEFAULTS = Path(__file__).resolve().parents[1] / "framework" / "defaults.yaml"
CFG = load_config(DEFAULTS)
GOOD = {**CFG["pins"], "runtime": "running"}

HAPPY = {
    "intake": ["ok"], "plan": ["ok"], "plan_gate": ["approved"], "implement": ["ok"],
    "precommit_review": ["pass"], "verify_author": ["ok"], "verify_run": ["pass"],
    "final_review": ["pass"], "remediate": ["ok"], "publish": ["ok"], "await_merge": ["merged"], "wiki_update": ["ok"],
}


def fake(script):
    """Per-state queue of outcomes; the last one repeats."""
    q = {k: list(v) for k, v in script.items()}

    def adapter(state):
        o = q[state]
        return o.pop(0) if len(o) > 1 else o[0]
    return adapter


def go(script, manifest=True, probes=GOOD, cfg=CFG):
    return run(cfg, fake({**HAPPY, **script}), lambda: manifest, probes)


def path(res):
    return [e["to"] for e in res.events if e["event"] == "transition"]


def test_happy_path():
    res = go({})
    assert res.final == "done"
    assert path(res) == ["plan", "plan_gate", "implement", "precommit_review", "verify_author",
                         "verify_run", "final_review", "publish", "await_merge", "wiki_update", "done"]


def test_failing_verify_remediates_then_mandatory_rereview():
    res = go({"verify_run": ["mismatch", "pass"], "remediate": ["ok"]})
    assert res.final == "done"
    p = path(res)
    i = p.index("remediate")
    assert p[i:i + 3] == ["remediate", "precommit_review", "verify_author"]


def test_every_edge_into_remediate_leads_only_to_precommit_review():
    assert TRANSITIONS["remediate"] == {"ok": "precommit_review"}


def test_missing_manifest_hard_stop():
    assert go({}, manifest=False).final == "blocked:no_manifest"


def test_remediation_cycles_capped():
    res = go({"verify_run": ["mismatch"]})
    assert res.final == "blocked:remediation_exhausted"
    assert path(res).count("remediate") == CFG["workflow"]["remediation"]["maxCycles"]


def test_worker_failure_retried_then_blocked():
    assert go({"plan": ["fail", "fail", "ok"]}).final == "done"
    assert go({"plan": ["fail"]}).final == "blocked:retries_exhausted"


def test_pending_human_gate_waits_not_fails():
    assert go({"plan_gate": ["pending"]}).final == "waiting:plan_gate"
    assert go({"await_merge": ["pending"]}).final == "waiting:await_merge"


def test_plan_rejected_returns_to_plan():
    res = go({"plan_gate": ["rejected", "approved"]})
    assert res.final == "done"
    assert path(res)[:4] == ["plan", "plan_gate", "plan", "plan_gate"]


def test_agent_merge_denied_and_audited():
    res = go({"await_merge": ["agent_merge", "merged"]})
    assert any(e["event"] == "denied" and e["action"] == "merge" for e in res.events)
    assert res.final == "done"
    assert "wiki_update" in path(res)


def test_agent_merge_never_advances():
    res = go({"await_merge": ["agent_merge"]})
    assert res.final == "blocked:step_limit"
    assert "wiki_update" not in path(res)


def test_unknown_outcome_blocks():
    assert go({"implement": ["bogus"]}).final == "blocked:bad_outcome:implement:bogus"


def test_runtime_down_blocks_before_any_launch():
    calls = []
    res = run(CFG, lambda s: calls.append(s) or "ok", lambda: True, {**GOOD, "runtime": "not_running"})
    assert res.final == "blocked:no_runtime"
    assert calls == []


@pytest.mark.parametrize("name", ["orca", "claude", "codex", "gh", "orcaAgentContextSchema"])
def test_version_drift_blocks_before_any_launch(name):
    calls = []
    res = run(CFG, lambda s: calls.append(s) or "ok", lambda: True, {**GOOD, name: "9.9.9"})
    assert res.final == "blocked:drift"
    assert calls == []
