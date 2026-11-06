"""Wiki support for a project repo: secret scan, raw ingest, lint.

Scan findings never contain the matched text, only file, line and pattern name.
"""
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import yaml

from cac.config import ConfigError
from cac.redact import PATTERNS

SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
LOG_HEADER = re.compile(r"^## \[\d{4}-\d{2}-\d{2}\] [a-z][a-z-]* \| .+$")
SKIP_DIRS = {".git", "repos"}


def scan_text(text):
    """Return [(line_no, pattern_name)] for lines that look like they hold a secret."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        hits += [(n, name) for name, rx in PATTERNS.items() if rx.search(line)]
    return hits


def _decode(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_project(project, staged=False):
    """Scan the project repo. Returns (findings, unscanned) where findings are
    (path, line, pattern) and unscanned lists non-text files that could not be checked."""
    root = Path(project).resolve()
    findings, unscanned = [], []
    if staged:
        r = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                           cwd=root, capture_output=True)
        if r.returncode:
            raise ConfigError(f"git diff --cached failed: {r.stderr.decode().strip()}")
        names = [n for n in r.stdout.decode().split("\0") if n]
        blobs = ((n, subprocess.run(["git", "show", f":{n}"], cwd=root, capture_output=True).stdout) for n in names)
    else:
        files = (p for p in sorted(root.rglob("*"))
                 if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts))
        blobs = ((str(p.relative_to(root)), p.read_bytes()) for p in files)
    for name, data in blobs:
        text = _decode(data)
        if text is None:
            unscanned.append(name)
            continue
        findings += [(name, line, pattern) for line, pattern in scan_text(text)]
    return findings, unscanned


def add_raw(project, source, file):
    """Copy `file` into wiki/raw/<source>/<date>-<name>, never overwriting, after a secret scan.

    Returns (dest_path, scanned). Nothing is copied when the scan finds something.
    """
    root = Path(project).resolve()
    src = Path(file)
    if not SOURCE_RE.match(source):
        raise ConfigError(f"invalid source name: {source}")
    if not src.is_file():
        raise ConfigError(f"not a file: {src}")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", src.name).lstrip(".") or "file"
    dest = root / "wiki" / "raw" / source / f"{date.today().isoformat()}-{name}"
    if dest.exists():
        raise ConfigError(f"raw files are immutable, already exists: {dest.relative_to(root)}")
    text = _decode(src.read_bytes())
    if text is not None:
        hits = scan_text(text)
        if hits:
            raise ConfigError("secret scan failed, nothing copied: "
                              + ", ".join(f"line {n} ({p})" for n, p in hits[:10]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    with open(root / "wiki" / "log.md", "a", encoding="utf-8") as f:
        f.write(f"\n## [{date.today().isoformat()}] ingest-raw | {source}/{dest.name}\n")
    return dest, text is not None


def _front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def lint(project):
    """Return a list of issue strings (empty when clean)."""
    wiki = Path(project).resolve() / "wiki"
    issues = []
    index = (wiki / "index.md").read_text(encoding="utf-8") if (wiki / "index.md").exists() else ""
    pages = sorted((wiki / "pages").rglob("*.md")) if (wiki / "pages").exists() else []
    for p in pages:
        rel = p.relative_to(wiki).as_posix()
        fm = _front_matter(p.read_text(encoding="utf-8"))
        if fm is None:
            issues.append(f"{rel}: missing or invalid front matter")
        else:
            if not fm.get("title"):
                issues.append(f"{rel}: front matter has no title")
            if not fm.get("sources"):
                issues.append(f"{rel}: front matter has no sources")
        if rel not in index:
            issues.append(f"{rel}: not listed in index.md")
    existing = {p.relative_to(wiki).as_posix() for p in pages}
    for target in re.findall(r"\]\((pages/[^)]+)\)", index):
        if target not in existing:
            issues.append(f"index.md: links to missing page {target}")
    log = wiki / "log.md"
    if log.exists():
        for n, line in enumerate(log.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("## ") and not LOG_HEADER.match(line):
                issues.append(f"log.md:{n}: malformed log header")
    return issues
