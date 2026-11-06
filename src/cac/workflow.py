"""Workflow state machine (T0: no Orca, no LLM).

The machine owns transitions, retry/remediation limits and the hard stops.
An adapter (real Orca-backed, or a fake in tests) only reports an outcome
string per state; it never chooses the next state.

verify_run is decided by the wrapper's verify_fn, never by the adapter.
"""
from dataclasses import dataclass, field

from cac.config import ConfigError

TRANSITIONS = {
    "intake": {"ok": "plan"},
    "plan": {"ok": "plan_gate"},
    "plan_gate": {"approved": "implement", "rejected": "plan"},
    "implement": {"ok": "precommit_review"},
    "precommit_review": {"pass": "verify_author", "findings": "implement"},
    "verify_author": {"ok": "verify_run"},
    "verify_run": {"pass": "final_review", "mismatch": "remediate"},
    "remediate": {"ok": "precommit_review"},  # re-review is mandatory: no other edge
    "final_review": {"pass": "publish", "findings": "remediate"},
    "publish": {"ok": "await_merge"},
    "await_merge": {"merged": "wiki_update"},
    "wiki_update": {"ok": "done"},
}
HUMAN_STATES = {"plan_gate", "await_merge"}
MAX_RETRIES = 2  # worker "fail" outcomes per state
MAX_STEPS = 200


@dataclass
class RunResult:
    final: str  # "done" | "waiting:<state>" | "blocked:<reason>"
    events: list = field(default_factory=list)


def preflight(config, probes):
    """Return None if safe to launch, else a 'blocked:<reason>' string."""
    if probes.get("runtime") != "running":
        return "blocked:no_runtime"
    for name, pinned in config["pins"].items():
        if probes.get(name) != pinned:
            return "blocked:drift"
    return None


def run(config, adapter, manifest_exists, probes, verify_fn):
    """adapter(state) -> outcome. manifest_exists() -> bool and
    verify_fn() -> ("pass"|"mismatch", step_results) are wrapper-side."""
    events = []

    def ev(**kw):
        events.append(kw)

    def blocked(reason):
        ev(event="blocked", reason=reason)
        return RunResult(f"blocked:{reason}", events)

    pre = preflight(config, probes)
    if pre:
        return blocked(pre.split(":", 1)[1])

    max_cycles = config["workflow"]["remediation"]["maxCycles"]
    state, retries, cycles = "intake", {}, 0
    for _ in range(MAX_STEPS):
        if state == "done":
            return RunResult("done", events)
        if state == "verify_run":
            try:
                outcome, results = verify_fn()
            except ConfigError:
                return blocked("bad_manifest")
            for r in results:
                ev(event="step_result", state=state, **r)
        else:
            outcome = adapter(state)
        ev(event="outcome", state=state, outcome=outcome)

        if outcome == "pending" and state in HUMAN_STATES:
            return RunResult(f"waiting:{state}", events)  # absence is not a decision
        if outcome.startswith("blocked:"):
            return blocked(outcome.split(":", 1)[1])
        if outcome == "agent_merge" and state == "await_merge":
            ev(event="denied", state=state, action="merge")  # merge.byAgent: forbidden
            continue
        if outcome == "fail" and state not in HUMAN_STATES:
            retries[state] = retries.get(state, 0) + 1
            if retries[state] > MAX_RETRIES:
                return blocked("retries_exhausted")
            continue
        if state == "verify_author" and outcome == "ok" and not manifest_exists():
            return blocked("no_manifest")

        nxt = TRANSITIONS[state].get(outcome)
        if nxt is None:
            return blocked(f"bad_outcome:{state}:{outcome}")
        if nxt == "remediate":
            cycles += 1
            if cycles > max_cycles:
                return blocked("remediation_exhausted")
        ev(event="transition", **{"from": state, "to": nxt})
        state = nxt
    return blocked("step_limit")
