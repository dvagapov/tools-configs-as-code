"""Publish a verified change as a branch and a draft PR; report whether a human merged it.

Nothing here merges. Repo hooks are disabled for the commit because the repo is untrusted input.
"""
import os
import re
import subprocess

from cac import wiki
from cac.config import ConfigError
from cac.project import _host_of, _origin

BOOKKEEPING = (".cac/plan.md", ".cac/review.md")


def _run(run, args, cwd, ok=(0,)):
    env = {**os.environ, "GIT_ALLOW_PROTOCOL": "ssh:https"}
    r = run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode not in ok:
        raise ConfigError(f"{' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "change"


def branch_name(config, run_id, task):
    name = config["branchPattern"].format(task_id=run_id, slug=_slug(task))
    if not re.fullmatch(r"agent/[A-Za-z0-9._/-]+", name) or ".." in name:
        raise ConfigError(f"invalid branch name: {name}")
    return name


def publish(repo, task, run_id, config, run=subprocess.run):
    """Commit the change on an agent branch, push it, open a draft PR. Returns the PR URL."""
    if _host_of(_origin(repo)) != "github":
        raise ConfigError("host_not_supported: only github is implemented")
    branch = branch_name(config, run_id, task)
    if _run(run, ["git", "symbolic-ref", "--short", "HEAD"], repo) != branch:
        _run(run, ["git", "checkout", "-q", "-b", branch], repo)
    _run(run, ["git", "add", "-A", "--", ".", *(f":(exclude){p}" for p in BOOKKEEPING)], repo)
    try:
        if run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode == 0:
            raise ConfigError("nothing_to_publish")
        findings, _ = wiki.scan_project(repo, staged=True)
        if findings:
            raise ConfigError("secret_scan: " + ", ".join(f"{p}:{n}" for p, n, _ in findings[:10]))
    except Exception:
        run(["git", "reset", "-q"], cwd=repo)
        raise
    title = task.strip().splitlines()[0][:72]
    _run(run, ["git", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", title], repo)
    _run(run, ["git", "push", "-u", "origin", branch], repo)
    pr = config.get("pr", {})
    cmd = ["gh", "pr", "create", "--base", config["baseBranch"], "--head", branch, "--title", title,
           "--body", f"Automated change from run {run_id}. A human reviews and merges this PR."]
    if pr.get("draft"):
        cmd.append("--draft")
    for label in pr.get("labels", []):
        cmd += ["--label", label]
    return _run(run, cmd, repo)


def merge_state(repo, branch, run=subprocess.run):
    """'merged' | 'pending' | 'blocked:pr_closed'. A human merges; this only reads."""
    state = _run(run, ["gh", "pr", "view", branch, "--json", "state", "-q", ".state"], repo)
    return {"MERGED": "merged", "OPEN": "pending", "CLOSED": "blocked:pr_closed"}.get(state, f"blocked:pr_state:{state}")
