# Task 01 — Orca Orchestration Discovery Report

Date: 2026-10-16. Scope: discovery and design only. Nothing implemented.

Labels: **Verified** means local CLI output or a fetched official doc. **Proposed** means a framework design choice; it is not a native Orca, Claude Code or Codex format. **Unverified** means not yet proven.

Related: [config-contracts.md](../design/config-contracts.md), [threat-model.md](../design/threat-model.md).

## 1. Executive recommendation

- Use Orca 1.4.197 as the **runtime and supervisor**. It owns worktrees, terminals, Run/Task/Dispatch state, gates, retries and recovery, through `orca orchestration ...` with `--json`.
- Build a thin framework wrapper (**Proposed**, working name `cac`) that owns only what Orca lacks:
  - config merge with locked invariants
  - workflow state machine
  - verification manifests
  - audit capture and redaction
  - CLI version and drift checks
- Merge enforcement belongs to Git hosting: GitHub rulesets or branch protection. **Neither repo has any today.** This is an open P0 gap; see §7.
- Git hosting goes through the local `gh` CLI (and `glab` for GitLab, not installed yet). No GitHub or GitLab MCP.
- Deterministic tests mostly run **without the Orca runtime**, against wrapper logic, Git fixtures and `orca agent-context --json` snapshots. Orca integration with a fake agent is **unverified** and needs a spike (Task 02).
- **Smallest viable end-to-end prototype:**
  - one workspace and one repo (`orca-workflow-fixture`)
  - wrapper-driven happy path: plan → implement → verify → review
  - one live run using real `claude` and `codex` through `orca orchestration worker-start`
  - Codex opens a PR from a disposable branch with `gh pr create`
  - a merge attempt without approval is rejected by a ruleset (the ruleset is enabled in a later, human-approved step)

## 2. Inventory

### Repositories

| Item | State | Evidence |
|---|---|---|
| `tools-configs-as-code` (local) | Branch `develop`, clean, only `README.md` and `LICENSE`; remote `git@github.com:dvagapov/tools-configs-as-code.git` | `git status -sb`, `git ls-files` |
| `orca-workflow-fixture` | Public, `develop` only, only `README.md`, Actions enabled, no workflows. Not cloned locally. | `gh repo view`, `gh api .../contents` |
| Branch protection and rulesets | **None on either repo**: `branches/develop/protection` returns 404 "Branch not protected", `/rulesets` returns `[]` | `gh api` (read-only) |
| `../orca` | Your fork of the Orca source (`dvagapov/orca`, branch `main`). Used only to find `orca.yaml` keys. | `git remote -v` |

### Tools (macOS 13.7.8)

| Tool | Version | Notes |
|---|---|---|
| orca | 1.4.197 | Runtime `not_running` at inspection time (`orca status --json`) |
| claude | 2.1.299 | |
| codex | codex-cli 0.163.0 | |
| gh | 2.92.0 | Two accounts; active `dvagapov`. Scopes `repo, read:org, gist, admin:public_key`. **No `workflow` scope.** |
| git | 2.52.0 | |
| glab | missing | |
| jq, node, python3, brew | 1.8.1, 24.11.1, 3.13.15, 7.0.8 | |

### Auth and integrations (presence only; no values read)

| Tool | Method | Evidence |
|---|---|---|
| Claude Code | claude.ai subscription OAuth, stored in the Keychain. No `ANTHROPIC_API_KEY` in the environment. | `claude auth status` |
| Codex | ChatGPT login; `~/.codex/auth.json` exists. No `OPENAI_API_KEY` or `CODEX_API_KEY` in the environment. | `codex login status` |
| gh | OAuth tokens in the keyring | `gh auth status` (masked) |

**Model traffic goes through a local proxy for both agents:**
- `~/.claude/settings.json` sets `env.ANTHROPIC_BASE_URL`.
- `~/.codex/config.toml` sets `model_provider` to a custom `caveman` provider.

**MCP servers:**
- `claude mcp list`: claude.ai connectors plus `caveman`.
- `codex mcp list`: `caveman` only.
- No GitHub, GitLab or Jira MCP servers are configured, and none are needed.

**Orca state:**
- Runtime state lives in `~/Library/Application Support/orca/` (`orchestration.db`, `logs/main.trace.ndjson`, `logs/daemon.log`, `agent-sessions/`, `terminal-history/`).
- Orca hook scripts live in `~/.orca/agent-hooks/`.
- Files that hold secrets must never be read or committed: `agent-session-authority.key`, `orca-e2ee-keypair.json`, `agent-hooks/endpoint.env`, and `codex-runtime-home/*auth*.json`.

## 3. Orca capability matrix

Evidence is the installed CLI unless a doc URL is cited. Docs base URL: `https://www.onorca.dev/docs`.

| Capability | Class | Evidence | Notes |
|---|---|---|---|
| Run namespace and inbox | native | `orchestration run-create --objective`, `run-use`, `run-show`, `run-list` | A Run never schedules workers |
| Tasks and DAG dependencies | native | `task-create --spec --deps <json_array> --parent`; skill reference `coordinator-loop.md` (`task-list --ready --brief`) | The docs page does not show `--deps`; the CLI does |
| Supervised worker launch | native | `worker-start (--task\|--spec) (--agent\|--terminal) --worktree current\|new-child\|new-top-level` | |
| Model and effort per launch | native | `worker-start --model <id> --effort <level>`; `--effort` requires `--model`; neither combines with `--terminal` | Installed note lists "Claude, Codex, and Cursor"; see §3a |
| Requested vs effective launch | native | `coordinator-loop.md`: compare `launch.requested` with `launch.effective` | Shows what Orca applied to the argv, not what the provider served |
| Retry | native | `worker-start --task <id> --retry-of <dispatch_id>`; placement not inherited | |
| Cancellation | native | `worker-stop`, `worker-abandon` | Only after positive proof of state (`recovery-and-cleanup.md`) |
| Idempotent mutations | native | `--retry-request <id>`, `request-show --request` | |
| Approval or decision gates | native | `gate-create --task --question --options`, `gate-resolve --id --resolution`, `gate-list` | A gate blocks a Task. It is not a merge control. |
| Blocking worker question | native | `ask`, `reply` | |
| Messaging and lifecycle | native | `send --type worker_done --outcome succeeded\|failed --task-id --dispatch-id --dispatch-capability` | `--dispatch-capability` exists in the `agent-context` flags but not in the `send` usage line |
| Wait and settle | native | `check --wait --types --ack --timeout-ms`; keepalive JSON goes to stderr | |
| Fleet and liveness | native | `worker-list --run`, `worker-show`, `worker-read --source auto\|transcript` | |
| State reset | native | `reset (--all\|--tasks\|--messages)` | Destructive to the user's real runtime; dedicated runtime only |
| Low-level dispatch | native | `dispatch --task --to [--inject] [--dry-run] [--return-preamble]`; `dispatch-show --preamble` | `--inject` makes an **unsupervised** lane (`low-level-topology.md`) |
| Worktrees | native | `worktree create --agent --prompt --setup --parent-worktree --no-parent`, `worktree set --comment --workspace-status` | |
| Repo config (`orca.yaml`) | native | Source `src/main/hooks.ts` `RECOGNIZED_ORCA_YAML_KEYS`: `scripts{setup,archive}`, `setupAgentStartupPolicy`, `issueCommand`, `defaultTabs`, `environmentRecipes`, `worktree`; docs `/model/worktrees` cover only `worktree.sharedDirectories` and `.worktreeinclude` | Per-repo only; there is no workspace-level layering |
| Environment recipes | native | `vm recipe doctor`; `environmentRecipes` key | Not needed for the MVP |
| Headless runtime | native | `orca serve [--port] [--no-pairing] [--project-root]` | CI viability **unverified**; the docs say service mode needs the app installed |
| Command schema for drift checks | native | `orca agent-context --json` gives `schemaVersion: 1` and 236 commands, without a runtime | Good input for a deterministic drift test |
| Version-matched guides | native | `skills get <name> [--reference]`, `skills list` | |
| Agent status hooks | native | `orca agent hooks status --json`; docs `/agents/hooks-memory` | Reports working/waiting/done status, not an audit stream |
| Repo `.claude/` and `.codex/` hooks | native (agent-side) | Docs `/agents/hooks-memory`: Orca "reads each repo's `.claude/` and `.codex/` configuration" | Prompt-injection surface; see the threat model |
| Rules, skill precedence, MCP management | wrapper required | Orca leaves `CLAUDE.md`/`AGENTS.md` alone (docs `/agents/hooks-memory`); no CLI for rules or MCP | The framework renders agent configs |
| Layered config common → workspace → repo | wrapper required | No Orca feature found | |
| Verification manifests | wrapper required | None in Orca | |
| Audit log and event stream | wrapper required | Docs describe none; `logs/main.trace.ndjson` exists, but its format is undocumented and not a contract | |
| Merge approval | unsupported in Orca | Gates are Task-scoped; merge belongs to Git hosting | |
| Automations | native, not in MVP | `automations create --trigger --prompt --provider --precheck` | |
| Accounts | native | `account list`, `account add` | Do not use in discovery; it changes auth |
| Arbitrary fake agent via `worker-start --agent` | unverified (likely unsupported) | Help text: `--agent` "Launch a known TUI agent" | §6 |
| Fake process via `terminal create --command` plus `dispatch` | unverified | CLI surface exists; worker verbs need the preamble's `--dispatch-capability` | Spike in Task 02 |
| Orchestration feature flag | unverified locally | Docs `/cli/orchestration`: "experimental", enabled under Settings → Experimental | Check before Task 02 |

### 3a. Docs vs installed 1.4.197 discrepancies

The docs site states no version. Every item below is in the docs but missing from the installed help, so the site most likely documents a newer build.

| Docs (URL) | Installed 1.4.197 | Impact |
|---|---|---|
| `/cli/orchestration`: `--model` for Claude, Codex, Muse, Cursor, Antigravity, OpenCode | `worker-start` note lists only "Claude, Codex, and Cursor" | Pin the Orca version; trust the CLI help |
| `/cli/reference`: `orca serve --supervise`, `orca serve service install\|status\|uninstall`, `serve restore resume` | `orca serve --help` has none of them; `orca serve service` gives "Unknown command" | No service-managed runtime on this version |
| `/cli/reference`: `automations create --extra-agent-args` | Missing from `automations create --help` | Automations cannot pass model flags here |
| `/cli/reference`: `worktree create --pr --gitlab-issue --gitlab-mr --reference` | Missing; installed has `--issue --linear-issue` | GitLab-linked worktrees unavailable |
| `/cli/orchestration`: no dependency flag documented | `task-create --deps` and `worker-start --deps` exist | Docs are incomplete |
| `/cli/orchestration`: `dispatch-show --preamble` | Exists; `dispatch --return-preamble` also exists | Consistent |
| `/model/worktrees`: only `worktree.sharedDirectories` | Source has 6 top-level keys | Docs are incomplete; treat the other keys as source-verified only |
| Docs: `orca agent hooks status\|on\|off` | Works, but is absent from top-level `orca --help` | Hidden command; use `agent-context` to detect it |

**Rule (Proposed):** the framework pins the Orca version. It treats `orca agent-context --json` from the pinned version as the contract, and the docs site as informative only.

## 4. Architecture and precedence (Proposed)

| Layer | Repo | Owns |
|---|---|---|
| Framework | `tools-configs-as-code` | Schemas, invariants, defaults, agent profiles, skills, workflows, wrapper, CI, generic acceptance tests |
| Workspace config | One per workspace (Git repo or directory) | Workspace manifest, overrides, sanitized audit records |
| Workspace wiki | One per workspace, shared by all its app repos | Karpathy-style `raw/`, wiki pages, `index.md`, `log.md` |
| Application repo | Each app | Code, tests, CI, `.cac/repo-policy.yaml` |

How precedence works:
- Values merge as common → workspace → repo: maps merge deeply, scalars are replaced by the later layer, and lists are replaced unless the schema marks them `append`.
- **Invariants** live in the framework under `locked:` and cannot be overridden by any layer. Examples:
  - no merge by agents
  - deny-listed agent flags
  - redaction on
  - human merge approval
- A violating override is a validation error (the wrapper exits non-zero). It is never silently ignored.
- Repo-supplied agent configs (`.claude/`, `.codex/`, `CLAUDE.md`, `AGENTS.md`) are untrusted input. They are not a precedence layer.
- Agent runtime configs are **rendered** from the merged config, so Claude settings and Codex profiles are generated, not hand-edited.

Schema examples are in [config-contracts.md](../design/config-contracts.md).

## 5. Workflow state machine (Proposed)

| # | State | Actor | Exit → next | Failure behavior |
|---|---|---|---|---|
| 1 | `intake` | Codex | Issue or brief normalized → `plan` | Bad input → `blocked` |
| 2 | `plan` | Claude, `opus`, effort `high` | Plan file → `plan_gate` | `worker_done --outcome failed` → retry ≤ 2 → `blocked` |
| 3 | `plan_gate` | Human, via `gate-create` / `gate-resolve` | approved → `implement`; rejected → `plan` | Timeout leaves it pending (absence is not a decision) |
| 4 | `implement` | Claude, `sonnet`, effort `medium` | Commits on the work branch → `precommit_review` | Same as #2 |
| 5 | `precommit_review` | Codex | pass → `verify_author`; findings → `implement` | |
| 6 | `verify_author` | Claude | Verification manifest and scripts → `verify_run` | Missing manifest → `blocked:no_manifest` (hard stop) |
| 7 | `verify_run` | Codex runs the manifest; the wrapper checks exit codes and artifacts | All expected → `final_review`; any mismatch → `remediate` | The wrapper, not the agent, decides pass/fail |
| 8 | `remediate` | Claude | Fix → `precommit_review` (**re-review is mandatory**) | More than N cycles → `blocked` |
| 9 | `final_review` | Codex, also reviews test quality | pass → `publish` | findings → `remediate` |
| 10 | `publish` | Codex: `git push` to the work branch, then `gh pr create` | PR URL → `await_merge` | Push rejected → `blocked:push_denied` |
| 11 | `await_merge` | Human | Merged on the host → `wiki_update` | Agent merge attempts are blocked by the host and logged |
| 12 | `wiki_update` | Codex | Wiki commit synced → `done` | Sync conflict → rebase or retry ≤ 3 → `blocked:wiki_conflict` |

Failures that apply to every state:
- **Launch failure:** `worker-start` exits non-zero. Read `failedStage` and `residualResources`, and follow the recovery table; never relaunch blindly.
- **Version drift:** if the `--version` output or the `agent-context` schema doesn't match the pins → `blocked:drift` before any launch.
- **Missing runtime:** if `orca status --json` reports the runtime unreachable → `blocked:no_runtime`. The wrapper never starts Orca on its own, unless config sets `runtime.autostart: true`.
- **Unverifiable worker:** keep waiting. Absence is never treated as failure.

## 6. Acceptance-test architecture

| Tier | When | Runs | Needs |
|---|---|---|---|
| T0 deterministic | Every PR, in framework CI | Wrapper unit and integration tests: config merge and invariants, manifest validation, redaction, state transitions with a fake agent adapter, Git fixtures in temporary repos, `agent-context` snapshot diff (snapshot committed from the pinned version) | No Orca runtime, no LLM, no network |
| T1 Orca integration | Locally on demand; CI only if headless `orca serve` proves viable | Real Orca runtime plus a fake worker process (if the Task 02 spike succeeds); gates; retry; `worker-stop`; `reset` on a **dedicated** runtime only | Orca app or `serve`, with the experimental orchestration setting on |
| T2 live | On demand, before releases or Orca/CLI upgrades | Real `claude` and `codex` against `orca-workflow-fixture` and a disposable branch or repo | Subscriptions, `gh`, rulesets enabled |

Fake-agent options:

| Option | Class | Evidence | Use |
|---|---|---|---|
| Wrapper adapter interface with a fake implementation | Proposed, native to the wrapper | — | T0 baseline |
| `worker-start --agent <fake>` | unverified (likely unsupported) | `--agent` = "known TUI agent" | — |
| Shim `claude`/`codex` binaries placed first on `PATH` | unverified | Not known whether Orca resolves agents via `PATH` or detects their TUIs | Spike |
| `terminal create --command <script>` + `dispatch --return-preamble` + script sends `worker_done` | unverified | CLI surface exists; lane is unsupervised | Spike |
| `dispatch --dry-run` | native, semantics unverified | `dispatch --help` | Smoke-test preambles |

Evidence rules:
- Assertions use exit codes, `git` state (`rev-parse`, `log`, `status --porcelain`), `gh api` JSON, Orca `--json` receipts, and audit files.
- An agent's own text is never evidence.

### Scenario matrix

| Scenario | Tier | Pass evidence |
|---|---|---|
| Valid and invalid config; precedence | T0 | Exit 0 or non-zero; golden output of the merged config |
| Locked-invariant override attempt | T0 | Non-zero exit; error names the key |
| Happy path: implement → review → verify | T0 (fake), T2 | State log shows the expected transitions; manifest artifacts exist; `worker_done` `succeeded` |
| Failing tests → remediate → mandatory re-review | T0, T2 | Transition `verify_run → remediate → precommit_review` appears; no skip |
| Missing verification manifest | T0 | `blocked:no_manifest`; non-zero exit |
| Permission denial or unauthorized action | T0 (policy), T2 (`permission_denials` in Claude `stream-json`) | Deny-listed flag refused before launch; denial recorded in audit |
| Synthetic-secret redaction | T0 | Planted `TEST_SECRET_…` absent from the audit; redaction counter > 0 |
| Multi-repo workspace sharing one wiki | T0 (Git fixtures), T2 | Both repos' runs append to the same wiki `log.md`; provenance includes the repo |
| Concurrent wiki updates and sync conflict | T0 | Two writers produce a rebase or retry; the final history is linear; no lost entries; or `blocked:wiki_conflict` |
| Branch push and PR creation | T2 (disposable repo or branch) | `git ls-remote` shows the branch; `gh pr view --json` state is `OPEN` |
| Merge without approval | T2 (needs a ruleset) | `gh pr merge` exits non-zero; PR stays `OPEN`; event audited |
| Missing runtime | T0 (stubbed `orca status`), T1 | `blocked:no_runtime` |
| Failed agent launch | T1 | `worker-start` exits 1; `failedStage` recorded; no duplicate launch |
| CLI or version drift | T0 | Changed `--version` or `agent-context` diff → `blocked:drift` |

## 7. Security, threat model and audit

Full detail: [threat-model.md](../design/threat-model.md). Key points:

- **P0 gap (unresolved):** `develop` on both repos has no branch protection and no rulesets. The active `gh` token has `repo` scope, so an agent could push to `develop` or merge with no human approval. Task 01 made no settings changes. A proposed enforcement test is in the threat model.
- **Verified risky flags**, which the framework deny-lists:
  - Claude: `--dangerously-skip-permissions`, `--permission-mode bypassPermissions`
  - Codex: `--dangerously-bypass-approvals-and-sandbox`, `-s danger-full-access`, `approval_policy=never` combined with a writable sandbox
- **Untrusted repos:** `claude -p` in an untrusted repo runs that repo's hooks and `.mcp.json` servers without prompting (headless docs).
- **Audit:** the MVP is append-only JSONL files in the workspace config repo, with Git history as the integrity record. A hash chain is deferred until the threat model justifies it (criteria are in the threat model).
- **Audit coverage is partial.** The threat model lists, per source, what can and cannot be observed. No completeness claim is made.

## 8. Implementation backlog

| ID | Item | Acceptance criteria |
|---|---|---|
| B0 | **Human:** enable rulesets on `develop` for both repos (PR required, ≥ 1 approval, block force-push and deletion, no bypass for the agent identity) | `gh api repos/<r>/rulesets` is non-empty; a direct push to `develop` is rejected; an unapproved `gh pr merge` fails |
| B1 | Task 02 spike: Orca fake-worker feasibility and the orchestration experimental flag | Written evidence for each fake-agent option in §6; T1 go/no-go |
| B2 | Rewrite root `README.md` and add `AGENTS.md` per the documentation conventions | README has purpose, one diagram and quick start; AGENTS.md has invariants and links |
| B3 | Config schemas (JSON Schema) and a merge engine with locked invariants | T0 config scenarios pass |
| B4 | Agent-profile renderer: Claude `--settings` file and Codex profile `$CODEX_HOME/<name>.config.toml` from merged config | Golden files; deny-listed flags never rendered |
| B5 | Wrapper state machine over `orca orchestration` with the pinned version, drift and runtime preflight | T0 state-machine and drift scenarios pass |
| B6 | Verification runner (manifest → exit codes and artifacts) | Missing-manifest and failing-test scenarios pass |
| B7 | Audit writer plus redactor | Redaction scenario passes; no raw transcripts in the repo |
| B8 | Wiki repo template and sync (`index.md`, `log.md`, provenance, rebase or retry) | Multi-repo and conflict scenarios pass |
| B9 | Framework CI (T0 on every PR) | Needs a `gh` token with `workflow` scope, or a push by a human |
| B10 | T2 live suite against the fixture and a disposable branch | All T2 rows pass; merge attempt rejected |
| B11 | Install `glab` and add GitLab parity | `glab mr create` path is tested on a disposable GitLab project |

**MVP = B0 + B1 + B3 + B5 + B6 + B7 + one T2 happy path.**

## 9. Open questions, assumptions and unsupported features

**Open questions:**
1. Is orchestration "experimental" enabled in your Orca settings? (unverified)
2. Can Orca drive a fake agent (§6)? This blocks T1.
3. Effective model and effort:
   - Claude `stream-json` `system/init` reports `model` (headless docs), and the `json` output includes a per-model cost breakdown. No effort field is documented.
   - Codex `--json` events report neither model nor effort (non-interactive docs).
   - Orca `launch.effective` reflects the launch argv only.
   - So the effective effort is **unobservable** from the provider side.
4. Model availability:
   - The Claude aliases `opus` and `sonnet` are verified in `claude --help`. Their mapping to Opus 5.5 and Sonnet 5.5 comes from the docs only; the full Sonnet 5.5 ID is unverified.
   - Codex models are listed only in the local `models_cache.json`, which is not proof of availability. The default model is unverified.
   - Requests go through local proxies, which may change the model served.
5. Codex exit codes are undocumented. This needs a T1 or T2 probe.
6. Which identity does the agent push with? The active `gh` user is the human (`dvagapov`), so rulesets cannot tell an agent push from a human push. Consider a separate bot account or fine-grained token (needs your decision).
7. Do workspace config repos and wiki repos live under GitHub `dvagapov/*`? Naming is undecided.

**Assumptions:**
- macOS only, single user.
- The Orca pin is 1.4.197 until a deliberate upgrade.

**Unsupported or not in scope:**
- Orca-native merge gates
- Orca-native layered config
- Orca-native audit stream
- the docs-only features in §3a
- Jira MCP (optional, later)
