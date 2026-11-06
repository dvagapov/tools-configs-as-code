import argparse
import sys

from cac import project
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

    a = p.parse_args(argv)
    try:
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


if __name__ == "__main__":
    sys.exit(main())
