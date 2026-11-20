import os
import stat
import subprocess
import sys

import pytest

from cac.cli import main
from cac.config import ConfigError
from cac.project import init
from cac.wiki import add_raw, lint, scan_project, scan_text

URL = "https://github.com/acme/web.git"
SECRET = "ghp_" + "a" * 36
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]


@pytest.fixture
def proj(tmp_path):
    return init(tmp_path / "acme", "acme", [f"web={URL}"])


def test_scan_text_reports_line_and_pattern_not_value():
    hits = scan_text(f"ok\nline two {SECRET}\n")
    assert hits == [(2, "github_token")]
    assert SECRET not in repr(hits)


def test_scan_project_finds_secret_and_skips_repos_and_git(proj):
    (proj / "wiki" / "raw" / "slack").mkdir()
    (proj / "wiki" / "raw" / "slack" / "dump.txt").write_text(f"hello\n{SECRET}\n")
    (proj / "repos" / "web").mkdir(parents=True)
    (proj / "repos" / "web" / "x.txt").write_text(SECRET)
    findings, _ = scan_project(proj)
    assert findings == [("wiki/raw/slack/dump.txt", 2, "github_token")]


def test_scan_project_reports_binary_as_unscanned(proj):
    (proj / "wiki" / "raw" / "doc.pdf").write_bytes(b"\xff\xfe\x00binary")
    findings, unscanned = scan_project(proj)
    assert findings == [] and unscanned == ["wiki/raw/doc.pdf"]


def test_staged_scan_reads_index_not_worktree(proj):
    f = proj / "wiki" / "pages" / "a.md"
    f.write_text(f"leak {SECRET}\n")
    subprocess.run(["git", "add", "-A"], cwd=proj, check=True)
    f.write_text("clean now\n")  # worktree is clean, the staged blob is not
    findings, _ = scan_project(proj, staged=True)
    assert findings == [("wiki/pages/a.md", 1, "github_token")]


def test_add_raw_copies_logs_and_is_immutable(proj, tmp_path):
    src = tmp_path / "chat.txt"
    src.write_text("meeting notes\n")
    dest, scanned = add_raw(proj, "slack", src)
    assert scanned and dest.read_text() == "meeting notes\n"
    assert dest.parent == proj / "wiki" / "raw" / "slack" and dest.name.endswith("-chat.txt")
    assert "ingest-raw | slack/" in (proj / "wiki" / "log.md").read_text()
    with pytest.raises(ConfigError, match="immutable"):
        add_raw(proj, "slack", src)


def test_add_raw_refuses_secret_and_copies_nothing(proj, tmp_path):
    src = tmp_path / "dump.txt"
    src.write_text(f"token {SECRET}\n")
    with pytest.raises(ConfigError, match="secret scan failed") as e:
        add_raw(proj, "slack", src)
    assert SECRET not in str(e.value)
    assert not (proj / "wiki" / "raw" / "slack").exists()
    assert "ingest-raw" not in (proj / "wiki" / "log.md").read_text()


def test_add_raw_binary_copied_but_flagged(proj, tmp_path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"\xff\xfe\x00pdf")
    dest, scanned = add_raw(proj, "files", src)
    assert dest.exists() and scanned is False


@pytest.mark.parametrize("source", ["../x", "Slack", "a/b", ""])
def test_add_raw_rejects_bad_source(proj, tmp_path, source):
    src = tmp_path / "f.txt"
    src.write_text("x")
    with pytest.raises(ConfigError):
        add_raw(proj, source, src)


def page(proj, name, body):
    (proj / "wiki" / "pages" / name).write_text(body)


GOOD = "---\ntitle: Checkout\nsources:\n  - raw: wiki/raw/slack/x.txt\n---\ntext\n"


def test_lint_clean_wiki(proj):
    page(proj, "checkout.md", GOOD)
    idx = proj / "wiki" / "index.md"
    idx.write_text(idx.read_text() + "[Checkout](pages/checkout.md) - flow\n")
    assert lint(proj) == []


def test_lint_reports_each_problem(proj):
    page(proj, "nofm.md", "just text\n")
    page(proj, "nosrc.md", "---\ntitle: T\n---\nx\n")
    idx = proj / "wiki" / "index.md"
    idx.write_text(idx.read_text() + "[Gone](pages/gone.md) - missing\n")
    log = proj / "wiki" / "log.md"
    log.write_text(log.read_text() + "\n## bad header\n## [2026-11-06] ingest-raw | slack/x\n")
    issues = lint(proj)
    for expected in ["nofm.md: missing or invalid front matter", "nosrc.md: front matter has no sources",
                     "pages/nofm.md: not listed in index.md", "links to missing page pages/gone.md",
                     "malformed log header"]:
        assert any(expected in i for i in issues), expected
    assert not any("2026-11-06" in i for i in issues)


def test_cli_scan_and_lint_exit_codes(proj, capsys):
    assert main(["scan", str(proj)]) == 0
    (proj / "wiki" / "pages" / "x.md").write_text(f"{SECRET}\n")
    assert main(["scan", str(proj)]) == 1
    out = capsys.readouterr().out
    assert "wiki/pages/x.md:1 (github_token)" in out and SECRET not in out
    assert main(["wiki", "lint", str(proj)]) == 1


def test_precommit_hook_blocks_secret_commit_and_allows_clean(proj, tmp_path, monkeypatch):
    hook = proj / ".git" / "hooks" / "pre-commit"
    assert hook.exists() and os.stat(hook).st_mode & stat.S_IXUSR
    shim = tmp_path / "bin" / "cac"
    shim.parent.mkdir()
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} -m cac \"$@\"\n")
    shim.chmod(0o755)
    env = {**os.environ, "PATH": f"{shim.parent}:{os.environ['PATH']}"}

    def commit():
        subprocess.run(["git", "add", "-A"], cwd=proj, check=True)
        return subprocess.run([*GIT, "commit", "-q", "-m", "x"], cwd=proj, env=env, capture_output=True, text=True)

    assert commit().returncode == 0
    (proj / "wiki" / "pages" / "leak.md").write_text(f"{SECRET}\n")
    r = commit()
    assert r.returncode != 0 and "SECRET?" in r.stderr  # git routes hook stdout to stderr

    env["PATH"] = "/usr/bin:/bin"  # no cac on PATH: fails closed
    (proj / "wiki" / "pages" / "leak.md").write_text("clean\n")
    r = commit()
    assert r.returncode != 0 and "cac not found" in r.stderr
