import subprocess

import pytest

from cac import gitops
from cac.config import ConfigError

CFG = {"baseBranch": "develop", "branchPattern": "agent/{task_id}", "pr": {"draft": True, "labels": ["agent"]}}


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "remote", "add", "origin", "https://github.com/o/fx.git")
    git(r, "commit", "-q", "--allow-empty", "-m", "i")
    git(r, "remote", "set-url", "--push", "origin", str(bare))  # push goes to the local bare repo
    (r / ".cac").mkdir()
    (r / ".cac" / "plan.md").write_text("plan")
    (r / ".cac" / "verify.yaml").write_text("steps")
    (r / "hello.py").write_text("def hello():\n    return 'hi'\n")
    return r


def runner(gh_out="https://github.com/o/fx/pull/1", log=None):
    log = [] if log is None else log
    def run(args, **kw):
        if args[0] == "gh":
            log.append(args)
            return type("R", (), {"returncode": 0, "stdout": gh_out, "stderr": ""})()
        if args[:2] == ["git", "push"]:
            kw["env"] = {**kw["env"], "GIT_ALLOW_PROTOCOL": "file:ssh:https"}
        return subprocess.run(args, **kw)
    return run


def test_publish_commits_source_and_manifest_not_bookkeeping(repo):
    log = []
    url = gitops.publish(repo, "Add hello", "r_1", CFG, runner(log=log))
    assert url.endswith("/pull/1")
    assert git(repo, "symbolic-ref", "--short", "HEAD").strip() == "agent/r_1"
    files = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(files) == [".cac/verify.yaml", "hello.py"]
    cmd = log[0]
    assert "--draft" in cmd and cmd[cmd.index("--base") + 1] == "develop" and cmd[cmd.index("--label") + 1] == "agent"


def test_publish_refuses_secrets_and_leaves_nothing_staged(repo):
    (repo / "k.txt").write_text("AKIAIOSFODNN7EXAMPLE\n")
    with pytest.raises(ConfigError, match="secret_scan"):
        gitops.publish(repo, "Add hello", "r_1", CFG, runner(log=[]))
    assert git(repo, "diff", "--cached", "--name-only").strip() == ""


def test_publish_with_no_changes_and_bad_branch(repo, tmp_path):
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "all")
    with pytest.raises(ConfigError, match="nothing_to_publish"):
        gitops.publish(repo, "t", "r_1", CFG, runner(log=[]))
    with pytest.raises(ConfigError, match="invalid branch"):
        gitops.branch_name({"branchPattern": "agent/{task_id}"}, "../x", "t")


def test_non_github_host_is_rejected(repo):
    git(repo, "remote", "set-url", "origin", "https://gitlab.com/o/fx.git")
    with pytest.raises(ConfigError, match="host_not_supported"):
        gitops.publish(repo, "t", "r_1", CFG, runner(log=[]))


@pytest.mark.parametrize("state,want", [("MERGED", "merged"), ("OPEN", "pending"), ("CLOSED", "blocked:pr_closed")])
def test_merge_state(repo, state, want):
    assert gitops.merge_state(repo, "agent/r_1", runner(gh_out=state)) == want
