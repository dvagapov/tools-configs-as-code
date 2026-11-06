"""Project repo lifecycle: `init` scaffolds it from the template, `sync` clones its app repos."""
import os
import re
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

import yaml

from cac.config import ConfigError, load_yaml, validate

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "framework" / "templates" / "project"
HOSTS = {"github.com": "github", "gitlab.com": "gitlab"}
URL_HOST = re.compile(r"^(?:git@([^:]+):|https://([^/]+)/)")


def _host_of(url):
    m = URL_HOST.match(url)
    host = (m.group(1) or m.group(2)) if m else None
    if host not in HOSTS:
        raise ConfigError(f"cannot infer github/gitlab host from url: {url}")
    return HOSTS[host]


def _git(*args, cwd=None, env=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)


def parse_repo(spec):
    name, sep, url = spec.partition("=")
    if not sep:
        raise ConfigError(f"--repo must be name=url, got: {spec}")
    return {"name": name, "url": url, "host": _host_of(url)}


def init(dest, name, repo_specs, framework_ref=None):
    """Scaffold a project repo at `dest` (must not exist or be empty) and `git init` it."""
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise ConfigError(f"{dest} exists and is not empty")
    workspace = {
        "schemaVersion": 1,
        "workspace": name,
        "frameworkRef": framework_ref or f"tools-configs-as-code@v{version('cac')}",
        "repos": [parse_repo(s) for s in repo_specs],
        "wiki": {"directPush": False},
    }
    validate("workspace", workspace, "workspace.yaml")  # before touching disk
    shutil.copytree(TEMPLATE_DIR, dest, dirs_exist_ok=True)
    for f in dest.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".yaml"):
            f.write_text(f.read_text().replace("{{workspace}}", name))
    (dest / "workspace.yaml").write_text(yaml.safe_dump(workspace, sort_keys=False))
    r = _git("init", "-q", "-b", "main", cwd=dest)
    if r.returncode:
        raise ConfigError(f"git init failed: {r.stderr.strip()}")
    hook = dest / ".git" / "hooks" / "pre-commit"
    hook.write_text(PRE_COMMIT)
    hook.chmod(0o755)
    return dest


PRE_COMMIT = """#!/bin/sh
# Installed by `cac project init`: block commits that contain secrets.
command -v cac >/dev/null 2>&1 || { echo "cac not found: refusing to commit without a secret scan" >&2; exit 1; }
exec cac scan --staged
"""


def _origin(path):
    r = _git("config", "--get", "remote.origin.url", cwd=path)  # raw value, no insteadOf rewrite
    return r.stdout.strip() if r.returncode == 0 else None


def sync(project_dir, allow_protocols="ssh:https"):
    """Clone missing app repos into <project>/repos/<name>; fetch (never merge) existing ones.

    Returns {name: ("cloned"|"fetched"|"error", detail)}. One failing repo does not stop the rest.
    """
    project = Path(project_dir).resolve()
    ws = load_yaml(project / "workspace.yaml")
    validate("workspace", ws, str(project / "workspace.yaml"))
    env = {**os.environ, "GIT_ALLOW_PROTOCOL": allow_protocols}  # refuses ext:: and other transports
    repos_dir = project / "repos"
    repos_dir.mkdir(exist_ok=True)
    out = {}
    for repo in ws["repos"]:
        target = repos_dir / repo["name"]
        if not target.exists():
            r = _git("clone", "--", repo["url"], str(target), env=env)
            out[repo["name"]] = ("cloned", "") if r.returncode == 0 else ("error", r.stderr.strip())
        elif not (target / ".git").exists():
            out[repo["name"]] = ("error", f"{target} exists and is not a git repo")
        elif _origin(target) != repo["url"]:
            out[repo["name"]] = ("error", f"origin is {_origin(target)}, expected {repo['url']}")
        else:
            r = _git("fetch", "--prune", cwd=target, env=env)
            out[repo["name"]] = ("fetched", "") if r.returncode == 0 else ("error", r.stderr.strip())
    return out
