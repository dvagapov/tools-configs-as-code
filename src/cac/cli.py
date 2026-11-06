import argparse
import sys

from cac import audit_review, project, publish, wiki
from cac.config import ConfigError


def main(argv=None):
    p = argparse.ArgumentParser(prog="cac")
    sub = p.add_subparsers(dest="group", required=True)
    pr = sub.add_parser("project").add_subparsers(dest="cmd", required=True)

    i = pr.add_parser("init", help="create a project repo from the template")
    i.add_argument("dest")
    i.add_argument("--name", required=True)
    i.add_argument("--repo", action="append", default=[], metavar="NAME=URL", required=True)
    i.add_argument("--framework-ref")

    s = pr.add_parser("sync", help="clone or fetch the project's app repos")
    s.add_argument("dir", nargs="?", default=".")

    pb = pr.add_parser("publish", help="commit wiki/audit changes on a branch and open a PR/MR (never merges)")
    pb.add_argument("-m", "--message", required=True)
    pb.add_argument("dir", nargs="?", default=".")

    au = sub.add_parser("audit").add_subparsers(dest="cmd", required=True)
    rv = au.add_parser("review", help="write audit/summaries/<run>.md from local audit data")
    rv.add_argument("run_id")
    rv.add_argument("--audit-dir", required=True)
    rv.add_argument("--project", default=".")
    rv.add_argument("--reviewer", choices=["none", "codex"], default="none")
    ak = au.add_parser("ack", help="acknowledge a high-severity summary (human, interactive terminal only)")
    ak.add_argument("run_id")
    ak.add_argument("--by", required=True)
    ak.add_argument("--project", default=".")
    gt = au.add_parser("gate", help="fail if a staged summary has an unacknowledged high-severity finding")
    gt.add_argument("--project", default=".")

    sc = sub.add_parser("scan", help="secret scan of a project repo")
    sc.add_argument("dir", nargs="?", default=".")
    sc.add_argument("--staged", action="store_true", help="scan staged content only (pre-commit)")

    wk = sub.add_parser("wiki").add_subparsers(dest="cmd", required=True)
    ar = wk.add_parser("add-raw", help="add an external source to wiki/raw/<source>/")
    ar.add_argument("source")
    ar.add_argument("file")
    ar.add_argument("--dir", default=".")
    li = wk.add_parser("lint", help="check wiki pages, index and log")
    li.add_argument("dir", nargs="?", default=".")

    a = p.parse_args(argv)
    try:
        if a.group == "scan":
            return _scan(a)
        if a.group == "wiki":
            return _wiki(a)
        if a.group == "audit":
            return _audit(a)
        if a.cmd == "publish":
            kind, out = publish.publish(a.dir, a.message)
            print(f"{kind}: {out}")
            return 0
        if a.cmd == "init":
            print(f"created {project.init(a.dest, a.name, a.repo, a.framework_ref)}")
            return 0
        results = project.sync(a.dir)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for name, (status, detail) in results.items():
        print(f"{status:8} {name}" + (f"  {detail}" if detail else ""))
    return 1 if any(s == "error" for s, _ in results.values()) else 0


def _scan(a):
    findings, unscanned = wiki.scan_project(a.dir, staged=a.staged)
    for path, line, pattern in findings:
        print(f"SECRET? {path}:{line} ({pattern})")
    for path in unscanned:
        print(f"unscanned (not text): {path}", file=sys.stderr)
    return 1 if findings else 0


def _audit(a):
    if a.cmd == "review":
        reviewer = audit_review.codex_reviewer if a.reviewer == "codex" else None
        path, sev = audit_review.review(a.run_id, a.audit_dir, a.project, reviewer=reviewer)
        print(f"{path} severity={sev}")
        return 0
    if a.cmd == "ack":
        if not sys.stdin.isatty():
            raise ConfigError("ack needs an interactive terminal: it is a human decision")
        audit_review.acknowledge(a.project, a.run_id, a.by)
        print("acknowledged")
        return 0
    blocked = audit_review.gate(a.project)
    for b in blocked:
        print(f"BLOCKED {b}: high severity, not acknowledged")
    return 1 if blocked else 0


def _wiki(a):
    if a.cmd == "add-raw":
        dest, scanned = wiki.add_raw(a.dir, a.source, a.file)
        print(f"added {dest}" + ("" if scanned else "  (not text: secret scan could not check it)"))
        return 0
    issues = wiki.lint(a.dir)
    for i in issues:
        print(i)
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
