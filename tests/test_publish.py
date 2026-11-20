import os
import subprocess

import pytest
import yaml

from cac.audit import AuditWriter
from cac.audit_review import acknowledge, review
from cac.config import ConfigError, load_config
from cac.project import init
from cac.publish import publish
from pathlib import Path

CFG = load_config(Path(__file__).resolve().parents[1] / "framework" / "defaults.yaml")
URL = "https://github.com/acme/proj.git"
SECRET = "ghp_" + "a" * 36
FILE_OK = "ssh:https:file"


def git(*a, cwd, check=True):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=cwd,
                          check=check, capture_output=True, text=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Project repo on main with an initial human commit, origin = local bare repo, gh/glab shims."""
    proj = init(tmp_path / "acme", "acme", ["web=https://github.com/acme/web.git"])
    git("add", "-A", cwd=proj)
    git("commit", "-q", "--no-verify", "-m", "initial", cwd=proj)
    bare = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    git("remote", "add", "origin", URL, cwd=proj)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{bare}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", URL)
    git("push", "-q", "origin", "main", cwd=proj)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "cli.log"
    for tool in ("gh", "glab"):
        shim = bin_ / tool
        shim.write_text(f'#!/bin/sh\necho "{tool} $@" >> {log}\necho https://example.test/pr/1\n')
        shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    return type("E", (), dict(proj=proj, bare=bare, log=log))


def heads(env):
    return git("branch", "--format=%(refname:short)", cwd=env.bare).stdout.split()


def add_page(proj, name="a.md", body="---\ntitle: A\nsources:\n  - raw: x\n---\ntext\n"):
    (proj / "wiki" / "pages" / name).write_text(body)
    idx = proj / "wiki" / "index.md"
    idx.write_text(idx.read_text() + f"[A](pages/{name}) - a\n")


def test_default_flow_pushes_branch_opens_pr_never_main(env):
    add_page(env.proj)
    before = git("rev-parse", "main", cwd=env.bare).stdout
    kind, out = publish(env.proj, "add checkout page", allow_protocols=FILE_OK)
    assert kind == "pr" and "example.test/pr/1" in out
    assert "wiki/" + __import__("datetime").date.today().isoformat() + "-add-checkout-page" in heads(env)
    assert git("rev-parse", "main", cwd=env.bare).stdout == before  # main on the remote untouched
    log = env.log.read_text()
    assert "gh pr create --base main --head wiki/" in log and "pr merge" not in log
    assert git("symbolic-ref", "--short", "HEAD", cwd=env.proj).stdout.strip() == "main"
    assert git("status", "--porcelain", cwd=env.proj).stdout == ""


def test_gitlab_origin_uses_glab(env):
    git("remote", "set-url", "origin", "git@gitlab.com:acme/proj.git", cwd=env.proj)
    git("config", "url.%s.insteadOf" % env.bare, "git@gitlab.com:acme/proj.git", cwd=env.proj)
    add_page(env.proj)
    publish(env.proj, "x", allow_protocols=FILE_OK)
    assert "glab mr create --target-branch main" in env.log.read_text()


def set_direct(proj):
    ws = yaml.safe_load((proj / "workspace.yaml").read_text())
    ws["wiki"]["directPush"] = True
    (proj / "workspace.yaml").write_text(yaml.safe_dump(ws, sort_keys=False))
    git("add", "-A", cwd=proj)
    git("commit", "-q", "--no-verify", "-m", "human enables direct push", cwd=proj)


def test_direct_push_goes_to_main_without_pr(env):
    set_direct(env.proj)
    add_page(env.proj)
    assert publish(env.proj, "solo", allow_protocols=FILE_OK) == ("pushed", "main")
    assert "wiki: solo" in git("log", "-1", "--format=%s", "main", cwd=env.bare).stdout
    assert not env.log.exists()


def test_changing_workspace_yaml_is_refused_even_in_same_change(env):
    ws = yaml.safe_load((env.proj / "workspace.yaml").read_text())
    ws["wiki"]["directPush"] = True  # an agent flips the switch in the same run
    (env.proj / "workspace.yaml").write_text(yaml.safe_dump(ws, sort_keys=False))
    add_page(env.proj)
    with pytest.raises(ConfigError, match="workspace.yaml changed"):
        publish(env.proj, "sneaky", allow_protocols=FILE_OK)
    assert heads(env) == ["main"]
    assert git("diff", "--cached", "--name-only", cwd=env.proj).stdout == ""  # unstaged again


def test_secret_blocks_publish(env):
    add_page(env.proj, body=f"---\ntitle: A\nsources: [x]\n---\n{SECRET}\n")
    with pytest.raises(ConfigError, match="secret scan failed") as e:
        publish(env.proj, "leak", allow_protocols=FILE_OK)
    assert SECRET not in str(e.value) and heads(env) == ["main"]


def test_lint_failure_blocks_publish(env):
    (env.proj / "wiki" / "pages" / "bad.md").write_text("no front matter\n")
    with pytest.raises(ConfigError, match="wiki lint failed"):
        publish(env.proj, "bad", allow_protocols=FILE_OK)


def test_unacknowledged_high_severity_blocks_then_ack_allows(env, tmp_path):
    w = AuditWriter(CFG, tmp_path / "audit", "r_1")
    w.append({"event": "denied", "state": "await_merge", "action": "merge"})
    review("r_1", tmp_path / "audit", env.proj)
    with pytest.raises(ConfigError, match="not acknowledged"):
        publish(env.proj, "audit", allow_protocols=FILE_OK)
    acknowledge(env.proj, "r_1", "me")
    assert publish(env.proj, "audit", allow_protocols=FILE_OK)[0] == "pr"


def test_nothing_to_publish_and_wrong_branch(env):
    with pytest.raises(ConfigError, match="nothing to publish"):
        publish(env.proj, "x", allow_protocols=FILE_OK)
    git("checkout", "-q", "-b", "other", cwd=env.proj)
    add_page(env.proj)
    with pytest.raises(ConfigError, match="runs from main"):
        publish(env.proj, "x", allow_protocols=FILE_OK)


def test_failed_pr_creation_surfaces_error(env, monkeypatch, tmp_path):
    bad = tmp_path / "bin2"
    bad.mkdir()
    (bad / "gh").write_text("#!/bin/sh\necho 'not logged in' >&2\nexit 1\n")
    (bad / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bad}:{os.environ['PATH']}")
    add_page(env.proj)
    with pytest.raises(ConfigError, match="not logged in"):
        publish(env.proj, "x", allow_protocols=FILE_OK)
