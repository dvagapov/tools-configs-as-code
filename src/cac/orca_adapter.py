"""Orca-backed workflow adapter (T1).

Claude states run as supervised Orca workers. Codex states and git/PR steps are
wrapper-side (see codex.py, gitops.py) because Orca launches Codex unsandboxed.
The machine owns every transition; this adapter only reports an outcome string
per state.
"""
import json
import re
import subprocess
import time
from pathlib import Path

from cac import codex, gitops, wiki
from cac.config import ConfigError

WORKER_STATES = {
    "plan": ("planner",
             "Task: {task}\nWrite a short implementation plan to .cac/plan.md. "
             "Change no other file and do not commit. Then stop."),
    "implement": ("implementer",
                  "Task: {task}\nImplement the plan in .cac/plan.md. "
                  "If .cac/review.md exists, also fix the findings in it. "
                  "Run Python with -B and leave no build artifacts (__pycache__, *.pyc). "
                  "Do not commit, push or edit .cac/. Then stop."),
    "remediate": ("implementer",
                  "Task: {task}\nVerification failed. Run each step in .cac/verify.yaml, find the failures and fix "
                  "the code, not the manifest. If .cac/review.md exists, also fix the findings in it. "
                  "Run Python with -B and leave no build artifacts (__pycache__, *.pyc). "
                  "Do not commit, push or edit .cac/. Then stop."),
}
WIKI_PROMPT = ("Task that was just completed in the app repo: {task}\nFollow AGENTS.md in this repository: add or "
               "update a page in wiki/pages/ describing the change, update wiki/index.md and wiki/log.md. "
               "Do not edit workspace.yaml or wiki/raw/. Do not commit. Then stop.")
FAILED = {"failed", "cancelled", "abandoned", "timed_out"}


def probe(run=subprocess.run):
    """Observed runtime status and tool versions, to compare against the pins."""
    def out(*cmd):
        try:
            return run(list(cmd), capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    def ver(text):
        m = re.search(r"\d+\.\d+\.\d+", text)
        return m.group(0) if m else None

    try:
        st = json.loads(out("orca", "status", "--json"))["result"]["runtime"]
    except (ValueError, KeyError):
        st = {}
    return {
        "runtime": "running" if st.get("state") == "ready" and st.get("reachable") else "down",
        "orca": st.get("appVersion"),
        "orcaAgentContextSchema": 1 if "orchestration.contract.v1" in st.get("capabilities", []) else None,
        "claude": ver(out("claude", "--version")),
        "codex": ver(out("codex", "--version")),
        "gh": ver(out("gh", "--version")),
    }


class OrcaAdapter:
    def __init__(self, repo_dir, task, run_id, config, profiles, approval_file, project=None,
                 run=subprocess.run, sleep=time.sleep, timeout_s=600, poll_s=5,
                 review=codex.run_review, author=codex.author_verification):
        self.repo = str(Path(repo_dir).resolve())
        self.project = str(Path(project).resolve()) if project else None
        self.task, self.run_id, self.config, self.profiles = task, run_id, config, profiles
        self.approval = Path(approval_file)
        self._run, self._sleep, self.timeout_s, self.poll_s = run, sleep, timeout_s, poll_s
        self._review, self._author = review, author
        self.coordinator = None
        self.pr = None

    def _orca(self, *args):
        r = self._run(["orca", *args, "--json"], capture_output=True, text=True, timeout=120)
        try:
            out = json.loads(r.stdout)
        except ValueError:
            raise ConfigError(f"orca {args[0]} {args[1]}: not JSON: {r.stdout[:200]!r}")
        if not out.get("ok"):
            raise ConfigError(f"orca {args[0]} {args[1]}: {out.get('error', {}).get('message', out)}")
        return out["result"]

    def _ensure_run(self):
        if self.coordinator:
            return
        self._orca("repo", "add", "--path", self.repo)  # registering an existing repo is a no-op
        self.coordinator = self._orca("terminal", "create", "--worktree", f"path:{self.repo}",
                                      "--title", "cac-coord")["terminal"]["handle"]
        self._orca("orchestration", "run-create", "--objective", self.task, "--from", self.coordinator)

    def close(self):
        if self.coordinator:
            self._run(["orca", "terminal", "close", "--terminal", self.coordinator], capture_output=True, text=True)
            self.coordinator = None

    def __call__(self, state):
        try:
            return self._state(state)
        except ConfigError as e:
            return f"blocked:{e}"  # a tool error is not a worker failure: stop, do not retry

    def _state(self, state):
        if state == "intake":
            return "ok"
        if state == "plan_gate":
            # The approval file lives outside the repo so a worker cannot create it.
            return "approved" if self.approval.is_file() else "pending"
        if state in WORKER_STATES:
            role, prompt = WORKER_STATES[state]
            return self._worker(role, prompt.format(task=self.task), self.repo)
        if state in ("precommit_review", "final_review"):
            return self._code_review()
        if state == "verify_author":
            return self._author(self.repo, self.task, self.profiles["verifier"])
        if state == "publish":
            self.pr = gitops.publish(self.repo, self.task, self.run_id, self.config, self._run)
            return "ok"
        if state == "await_merge":
            return gitops.merge_state(self.repo, gitops.branch_name(self.config, self.run_id, self.task), self._run)
        if state == "wiki_update":
            return self._wiki_update()
        return f"blocked:unknown_state:{state}"

    def _worker(self, role, prompt, repo):
        p = self.profiles[role]
        args = ["orchestration", "worker-start", "--spec", prompt, "--agent", p["agent"],
                "--worktree", f"path:{repo}", "--timeout-ms", str(self.timeout_s * 1000)]
        for flag in ("model", "effort"):
            if p.get(flag):
                args += [f"--{flag}", p[flag]]
        self._ensure_run()
        if repo != self.repo:
            self._orca("repo", "add", "--path", repo)
        return self._wait(self._orca(*args, "--from", self.coordinator)["dispatchId"])

    def _code_review(self):
        outcome, text = self._review(self.repo, self.task, self.profiles["reviewer"])
        notes = Path(self.repo) / ".cac" / "review.md"
        if outcome == "findings":  # the next implement/remediate worker reads these
            notes.write_text(text, encoding="utf-8")
        elif outcome == "pass":
            notes.unlink(missing_ok=True)
        return outcome

    def _wiki_update(self):
        if not self.project:
            return "ok"  # no project repo given: nothing to update
        outcome = self._worker("implementer", WIKI_PROMPT.format(task=self.task), self.project)
        if outcome != "ok":
            return outcome
        return "fail" if wiki.lint(self.project) else "ok"

    def _wait(self, dispatch):
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            state = self._orca("orchestration", "worker-show", "--dispatch", dispatch)["worker"]["state"]
            if state == "succeeded":
                return "ok"
            if state in FAILED:
                return "fail"
            self._sleep(self.poll_s)
        return "fail"
