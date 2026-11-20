"""W5: publish wiki/audit changes from a project repo.

Default: commit on a new branch, push the branch and open a PR/MR. A human merges.
`wiki.directPush: true` in workspace.yaml (solo use) pushes straight to main instead.
Nothing here merges anything.
"""
import os
import re
import subprocess
from datetime import date
from pathlib import Path

from cac import audit_review, wiki
from cac.config import ConfigError, load_yaml, validate
from cac.project import _git, _host_of, _origin

BASE = "main"


def _run(args, cwd, env=None, ok=(0,)):
    r = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode not in ok:
        raise ConfigError(f"{' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "update"


def _checks(root):
    """Everything the pre-commit hook enforces, run on the staged set."""
    findings, _ = wiki.scan_project(root, staged=True)
    if findings:
        raise ConfigError("secret scan failed: " + ", ".join(f"{p}:{n}" for p, n, _ in findings[:10]))
    issues = wiki.lint(root)
    if issues:
        raise ConfigError("wiki lint failed: " + "; ".join(issues[:10]))
    blocked = audit_review.gate(root)
    if blocked:
        raise ConfigError("high-severity audit summary not acknowledged: " + ", ".join(blocked))


def publish(project, message, allow_protocols="ssh:https"):
    """Returns ("pr", output) or ("pushed", "main")."""
    root = Path(project).resolve()
    ws = load_yaml(root / "workspace.yaml")
    validate("workspace", ws, "workspace.yaml")
    direct = ws.get("wiki", {}).get("directPush", False)
    env = {**os.environ, "GIT_ALLOW_PROTOCOL": allow_protocols}

    if _run(["git", "symbolic-ref", "--short", "HEAD"], root) != BASE:
        raise ConfigError(f"publish runs from {BASE}")
    _run(["git", "add", "-A"], root)
    try:
        names = _run(["git", "diff", "--cached", "--name-only"], root).splitlines()
        if not names:
            raise ConfigError("nothing to publish")
        if "workspace.yaml" in names:  # agents never change it; a human commits it by hand
            raise ConfigError("workspace.yaml changed: commit it by hand, it is never published automatically")
        _checks(root)
    except Exception:
        _git("reset", "-q", cwd=root)
        raise

    commit = ["git", "commit", "-q", "--no-verify", "-m", f"wiki: {message}"]  # checks already ran above
    if direct:
        _run(commit, root)
        _run(["git", "push", "origin", f"HEAD:refs/heads/{BASE}"], root, env=env)
        return "pushed", BASE

    branch = f"wiki/{date.today().isoformat()}-{_slug(message)}"
    _run(["git", "checkout", "-q", "-b", branch], root)
    _run(commit, root)
    _run(["git", "push", "-u", "origin", branch], root, env=env)
    _run(["git", "checkout", "-q", BASE], root)  # leave the repo on main for the next publish
    body = "Changed files:\n" + "\n".join(f"- {n}" for n in names) + "\n\nA human reviews and merges this PR."
    if _host_of(_origin(root)) == "github":
        out = _run(["gh", "pr", "create", "--base", BASE, "--head", branch, "--title", f"wiki: {message}",
                    "--body", body], root)
    else:
        out = _run(["glab", "mr", "create", "--target-branch", BASE, "--source-branch", branch,
                    "--title", f"wiki: {message}", "--description", body, "--yes"], root)
    return "pr", out
