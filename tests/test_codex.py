import subprocess

from cac.codex import author_verification, fingerprint, run_review


def fake(text, code=0, edit=None):
    def run(cmd, **kw):
        assert cmd[:3] == ["codex", "exec", "-s"] and cmd[3] in ("read-only", "workspace-write")
        if text is not None:
            open(cmd[cmd.index("-o") + 1], "w").write(text)
        if edit:
            edit()
        return type("R", (), {"returncode": code})()
    return run


def go(text, code=0):
    return run_review("/r", "t", {"effort": "high"}, run=fake(text, code))[0]


def test_review_verdicts_use_a_read_only_sandbox():
    seen = []
    run_review("/r", "t", {}, run=lambda cmd, **kw: seen.append(cmd) or type("R", (), {"returncode": 1})())
    assert seen[0][:4] == ["codex", "exec", "-s", "read-only"]
    assert go("fine\nVERDICT: PASS\n") == "pass"
    assert go("bug\nVERDICT: FINDINGS") == "findings"


def test_missing_or_malformed_verdict_or_exit_is_fail():
    assert go("looks good") == "fail"
    assert go("VERDICT: PASS and more") == "fail"
    assert go(None) == "fail"
    assert go("VERDICT: PASS", code=1) == "fail"


def test_effort_and_model_flags():
    seen = {}
    run_review("/r", "t", {"model": "m", "effort": "high"},
               run=lambda cmd, **kw: seen.update(cmd=cmd) or type("R", (), {"returncode": 1})())
    assert "-m" in seen["cmd"] and 'model_reasoning_effort="high"' in seen["cmd"]


def git_repo(tmp_path):
    for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / ".cac").mkdir()
    return tmp_path


def test_fingerprint_ignores_cac_but_sees_source(tmp_path):
    repo = git_repo(tmp_path)
    before = fingerprint(repo)
    (repo / ".cac" / "verify.yaml").write_text("steps")
    assert fingerprint(repo) == before
    (repo / "a.py").write_text("x = 2\n")
    assert fingerprint(repo) != before


def test_verifier_may_only_add_the_manifest(tmp_path):
    repo = git_repo(tmp_path)
    add = lambda: (repo / ".cac" / "verify.yaml").write_text("steps")
    assert author_verification(repo, "t", {}, run=fake("", edit=add)) == "ok"
    tamper = lambda: (repo / "a.py").write_text("x = 3\n")
    assert author_verification(repo, "t", {}, run=fake("", edit=tamper)) == "blocked:verifier_changed_source"
    assert author_verification(repo, "t", {}, run=fake("", code=1)) == "fail"
