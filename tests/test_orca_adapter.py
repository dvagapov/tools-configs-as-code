import json

from cac.orca_adapter import OrcaAdapter, probe

PROFILES = {"planner": {"agent": "claude", "model": "opus", "effort": "high"},
            "implementer": {"agent": "claude", "model": None},
            "reviewer": {"agent": "codex", "effort": "high"},
            "verifier": {"agent": "codex"}}
CONFIG = {"baseBranch": "develop", "branchPattern": "agent/{task_id}"}


def make(tmp_path, states=(), ok=True, **kw):
    calls, states = [], list(states)

    def run(cmd, **k):
        calls.append(cmd)
        sub = cmd[2] if len(cmd) > 2 else ""
        if cmd[1] == "terminal" and sub == "create":
            res = {"terminal": {"handle": "term_c"}}
        elif sub == "worker-start":
            res = {"dispatchId": "ctx_1"}
        elif sub == "worker-show":
            res = {"worker": {"state": states.pop(0)}}
        else:
            res = {}
        return type("R", (), {"stdout": json.dumps({"ok": ok, "result": res, "error": {"message": "boom"}})})()

    a = OrcaAdapter(tmp_path, "do x", "r_1", CONFIG, PROFILES, tmp_path / "r.approved", run=run,
                    sleep=lambda s: None, timeout_s=60, **kw)
    return a, calls


def test_intake_runs_no_worker(tmp_path):
    a, calls = make(tmp_path)
    assert a("intake") == "ok" and calls == []


def test_plan_worker_success_passes_profile_flags(tmp_path):
    a, calls = make(tmp_path, ["running", "succeeded"])
    assert a("plan") == "ok"
    start = next(c for c in calls if "worker-start" in c)
    assert start[start.index("--agent") + 1] == "claude"
    assert start[start.index("--model") + 1] == "opus" and "--effort" in start
    assert "--from" in start and "term_c" in start


def test_worker_failure_is_fail_and_orca_error_blocks(tmp_path):
    a, _ = make(tmp_path, ["failed"])
    assert a("implement") == "fail"
    a, _ = make(tmp_path, ok=False)
    assert a("plan").startswith("blocked:") and "boom" in a("plan")


def test_remediate_uses_the_implementer_worker(tmp_path):
    a, calls = make(tmp_path, ["succeeded"])
    assert a("remediate") == "ok"
    spec = next(c for c in calls if "worker-start" in c)
    assert "Verification failed" in spec[spec.index("--spec") + 1]


def test_gate_waits_until_approval_file_exists(tmp_path):
    a, _ = make(tmp_path)
    assert a("plan_gate") == "pending"
    (tmp_path / "r.approved").write_text("")
    assert a("plan_gate") == "approved"


def test_both_review_states_share_the_findings_file(tmp_path):
    (tmp_path / ".cac").mkdir()
    a, calls = make(tmp_path)
    a._review = lambda repo, task, profile: ("findings", "bug at x")
    for state in ("precommit_review", "final_review"):
        assert a(state) == "findings" and calls == []
    assert (tmp_path / ".cac" / "review.md").read_text() == "bug at x"
    a._review = lambda repo, task, profile: ("pass", "ok")
    assert a("final_review") == "pass"
    assert not (tmp_path / ".cac" / "review.md").exists()  # stale notes must not outlive a pass


def test_verify_author_uses_the_verifier_profile(tmp_path):
    seen = []
    a, calls = make(tmp_path, author=lambda repo, task, profile: seen.append(profile) or "ok")
    assert a("verify_author") == "ok" and seen == [PROFILES["verifier"]] and calls == []


def test_publish_records_pr_and_errors_block(tmp_path, monkeypatch):
    from cac import gitops
    a, _ = make(tmp_path)
    monkeypatch.setattr(gitops, "publish", lambda *args: "https://x/pr/1")
    assert a("publish") == "ok" and a.pr == "https://x/pr/1"

    def boom(*args):
        raise gitops.ConfigError("secret_scan: a:1")
    monkeypatch.setattr(gitops, "publish", boom)
    assert a("publish") == "blocked:secret_scan: a:1"


def test_await_merge_maps_pr_state(tmp_path, monkeypatch):
    from cac import gitops
    a, _ = make(tmp_path)
    seen = {}
    monkeypatch.setattr(gitops, "merge_state", lambda repo, branch, run: seen.update(b=branch) or "pending")
    assert a("await_merge") == "pending" and seen["b"] == "agent/r_1"


def test_wiki_update_skips_without_project_and_lints_with_one(tmp_path, monkeypatch):
    from cac import wiki
    a, _ = make(tmp_path)
    assert a("wiki_update") == "ok"
    proj = tmp_path / "proj"
    proj.mkdir()
    a, calls = make(tmp_path, ["succeeded"], project=proj)
    monkeypatch.setattr(wiki, "lint", lambda p: [])
    assert a("wiki_update") == "ok"
    assert any("worker-start" in c and f"path:{proj.resolve()}" in c for c in calls)
    a, _ = make(tmp_path, ["succeeded"], project=proj)
    monkeypatch.setattr(wiki, "lint", lambda p: ["bad page"])
    assert a("wiki_update") == "fail"


def test_probe_reads_versions_and_runtime():
    status = json.dumps({"result": {"runtime": {"state": "ready", "reachable": True, "appVersion": "1.4.197",
                                                "capabilities": ["orchestration.contract.v1"]}}})
    outs = {"orca": status, "claude": "2.1.327 (Claude Code)", "codex": "codex-cli 0.163.0", "gh": "gh version 2.92.0 (x)"}
    p = probe(run=lambda cmd, **kw: type("R", (), {"stdout": outs[cmd[0]]})())
    assert p == {"runtime": "running", "orca": "1.4.197", "orcaAgentContextSchema": 1,
                 "claude": "2.1.327", "codex": "0.163.0", "gh": "2.92.0"}
