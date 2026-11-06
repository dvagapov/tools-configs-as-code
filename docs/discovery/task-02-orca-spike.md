# Task 02 — Orca fake-worker spike (B1)

Date: 2026-11-06. Orca 1.4.197, headless `orca serve --no-pairing`, throwaway repo. All results are **Verified** by local CLI output unless marked otherwise.

## Result: no-go for a fake supervised worker

| Question | Result | Evidence |
|---|---|---|
| Orchestration "experimental" flag | No gate seen in headless mode. `run-create`, `task-create`, `dispatch --dry-run` all worked. (Desktop Settings → Experimental not checked.) | CLI calls |
| Orchestration needs a coordinator terminal | Yes. Without one: `no_active_sender_terminal`. Create a terminal and pass `--from <handle>` (or set `ORCA_TERMINAL_HANDLE`). `worker-list` does not accept `--from`. | `run-create` |
| `worker-start --terminal` on a plain script | Rejected: `agent_unconfigured` ("not running a recognized agent") | `worker-start` |
| Shim binary named `claude` placed in a terminal | Recognized (`ok: true`) but the worker ends `failed` at stage `agent_readiness`, liveness `unverifiable / missing_status` | `worker-list` |
| `task-create` + `dispatch --dry-run` to an unsupervised terminal | Works (`ok: true`) | CLI calls |

Reading: Orca recognizes an agent by command name, then waits for agent status signals (its hooks) that a shim never sends. A fake supervised worker would have to imitate those signals. That is an undocumented internal contract, so not worth building.

## Decision

- T0 stays the baseline: the wrapper's fake adapter (`cac.workflow.run` with a scripted adapter). It already covers the state machine, retries, gates and blocks.
- T1 (Orca integration) uses **real** `claude` / `codex` workers with tiny prompts, run on demand locally. Not in CI.
- Unsupervised `dispatch` + a script is usable only for smoke-testing Task/Dispatch bookkeeping, not worker lifecycle.

## Side effects and risks seen

- **`orca serve` bound `ws://0.0.0.0:6768`** (all interfaces) even with `--no-pairing`. Pairing was disabled, but the listener was not loopback-only. Treat headless serve as a risk on untrusted networks; stop it right after use.
- Starting the runtime made Orca write Codex hook trust entries (`[codex-trust-grant] granted 8 managed hook entries ... wrote=true`) into your Codex configuration. That is a change to `~/.codex` state outside this repo.
- The runtime used the real Orca data dir. The spike's repo, run and terminals were closed; the server was stopped (`orca status` → `not_running`). The run and task rows remain in `orchestration.db`.
- The `opencode` session scan logged a harmless missing-database error.

## Still unverified

- A real `claude`/`codex` worker through `worker-start --agent` (needs auth; Codex login is done, a live launch was not attempted).
- Desktop-app experimental setting.
- Codex exit codes.
