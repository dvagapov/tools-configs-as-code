import subprocess
from pathlib import Path

import pytest
import yaml

from cac.cli import main
from cac.config import ConfigError, validate
from cac.project import init, parse_repo, sync

URL = "https://github.com/acme/web.git"
URL2 = "git@gitlab.com:acme/ops.git"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]


def git(*a, cwd=None):
    subprocess.run([*GIT, *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def remotes(tmp_path, monkeypatch):
    """Two fake remotes: URLs rewritten to local bare repos via git's insteadOf."""
    cfg = []
    for url, name in ((URL, "web"), (URL2, "ops")):
        work = tmp_path / f"src-{name}"
        work.mkdir()
        git("init", "-q", "-b", "main", cwd=work)
        (work / "f").write_text(name)
        git("add", ".", cwd=work)
        git("commit", "-q", "-m", "init", cwd=work)
        bare = tmp_path / f"{name}.git"
        git("clone", "-q", "--bare", str(work), str(bare))
        cfg.append((url, bare))
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(len(cfg)))
    for n, (url, bare) in enumerate(cfg):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{n}", f"url.{bare}.insteadOf")
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{n}", url)
    return cfg


def make(tmp_path):
    return init(tmp_path / "acme", "acme", [f"web={URL}", f"ops={URL2}"])


def test_init_layout_and_valid_workspace(tmp_path):
    p = make(tmp_path)
    for rel in ["workspace.yaml", "AGENTS.md", ".gitignore", "wiki/index.md", "wiki/log.md", "wiki/raw/.gitkeep",
                "wiki/pages/.gitkeep", "audit/summaries/.gitkeep", "incidents/observability.md",
                "incidents/alerts/.gitkeep", "incidents/postmortems/.gitkeep", ".git"]:
        assert (p / rel).exists(), rel
    ws = yaml.safe_load((p / "workspace.yaml").read_text())
    validate("workspace", ws, "t")
    assert ws["repos"][1] == {"name": "ops", "url": URL2, "host": "gitlab"}
    assert ws["wiki"] == {"directPush": False}
    assert "{{workspace}}" not in (p / "AGENTS.md").read_text() and "acme" in (p / "AGENTS.md").read_text()


def test_init_gitignore_keeps_repos_and_raw_audit_out(tmp_path):
    p = make(tmp_path)
    git("add", "-A", cwd=p)
    (p / "repos" / "web").mkdir(parents=True)
    (p / "repos" / "web" / "x").write_text("x")
    (p / "audit" / "runs").mkdir()
    (p / "audit" / "runs" / "r1.jsonl").write_text("{}")
    tracked = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=p,
                             capture_output=True, text=True).stdout
    assert "repos/" not in tracked and "runs" not in tracked


def test_init_refuses_non_empty_dir_and_bad_input(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "f").write_text("1")
    with pytest.raises(ConfigError, match="not empty"):
        init(tmp_path / "x", "acme", [f"web={URL}"])
    for bad_name in ("Bad Name", "../x"):
        with pytest.raises(ConfigError):
            init(tmp_path / "y", bad_name, [f"web={URL}"])
    assert not (tmp_path / "y").exists()  # validation happens before touching disk


@pytest.mark.parametrize("spec", ["noequals", "web=file:///etc/passwd", "web=ext::sh -c id", "web=--upload-pack=x",
                                  "web=https://example.com/o/r.git", "../x=https://github.com/o/r.git",
                                  "a/b=https://github.com/o/r.git"])
def test_unsafe_or_unknown_repo_specs_rejected(tmp_path, spec):
    with pytest.raises(ConfigError):
        init(tmp_path / "p", "acme", [spec])


def test_sync_clones_then_fetches(tmp_path, remotes):
    p = make(tmp_path)
    r = sync(p, allow_protocols="ssh:https:file")
    assert r == {"web": ("cloned", ""), "ops": ("cloned", "")}
    assert (p / "repos" / "web" / "f").read_text() == "web"
    assert sync(p, allow_protocols="ssh:https:file") == {"web": ("fetched", ""), "ops": ("fetched", "")}


def test_sync_never_touches_local_changes(tmp_path, remotes):
    p = make(tmp_path)
    sync(p, allow_protocols="ssh:https:file")
    (p / "repos" / "web" / "f").write_text("local edit")
    sync(p, allow_protocols="ssh:https:file")
    assert (p / "repos" / "web" / "f").read_text() == "local edit"


def test_sync_reports_per_repo_errors_and_continues(tmp_path, remotes):
    p = make(tmp_path)
    (p / "repos" / "web").mkdir(parents=True)  # exists, not a git repo
    r = sync(p, allow_protocols="ssh:https:file")
    assert r["web"][0] == "error" and "not a git repo" in r["web"][1]
    assert r["ops"] == ("cloned", "")


def test_sync_origin_mismatch_is_error(tmp_path, remotes):
    p = make(tmp_path)
    sync(p, allow_protocols="ssh:https:file")
    subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/evil/x.git"],
                   cwd=p / "repos" / "web", check=True)
    assert sync(p, allow_protocols="ssh:https:file")["web"][0] == "error"


def test_default_protocol_allowlist_blocks_file_transport(tmp_path, remotes):
    p = make(tmp_path)
    r = sync(p)  # default ssh:https only; the rewritten local path is a file transport
    assert r["web"][0] == "error"


def test_sync_rejects_hand_edited_unsafe_workspace(tmp_path):
    p = make(tmp_path)
    ws = yaml.safe_load((p / "workspace.yaml").read_text())
    ws["repos"][0]["url"] = "ext::sh -c touch /tmp/pwned"
    (p / "workspace.yaml").write_text(yaml.safe_dump(ws))
    with pytest.raises(ConfigError):
        sync(p)


def test_cli_init_and_sync_exit_codes(tmp_path, remotes, capsys):
    dest = tmp_path / "cli"
    assert main(["project", "init", str(dest), "--name", "cli", "--repo", f"web={URL}"]) == 0
    assert main(["project", "init", str(dest), "--name", "cli", "--repo", f"web={URL}"]) == 2
    assert main(["project", "sync", str(dest)]) == 1  # default protocols block the local fake remote
    assert "error" in capsys.readouterr().out
