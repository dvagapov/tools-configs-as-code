# Threat Model and Audit Design (Proposed)

Status: design only. Facts are marked **Verified** with their evidence. Everything else is a proposal.

## Trust boundaries

| Boundary | Trusted side | Untrusted side |
|---|---|---|
| Framework repo | Locked invariants, rendered agent configs | Workspace and repo overrides (validated) |
| App repo content | — | Code, docs, `CLAUDE.md`/`AGENTS.md`, `.claude/`, `.codex/`, `.mcp.json`, issue and PR text |
| Agent process | Wrapper-chosen argv and rendered settings | Model output and tool calls |
| Model traffic | — | Local proxies (`ANTHROPIC_BASE_URL`, Codex `caveman` provider) **Verified** |
| Git hosting | Rulesets and required human review | Agent-held `gh` token |

## Threats and controls

| Threat | Control (Proposed unless marked) |
|---|---|
| Prompt injection via repo files, issues or PR comments | Agents treat repo text as data. The wrapper renders its own settings and passes `--setting-sources` or `--settings` (Claude, **Verified flags**) so repo settings layers aren't trusted. Verification pass/fail comes from wrapper-checked exit codes, never agent claims. |
| Malicious repo hooks or MCP servers | **Verified:** `claude -p` runs a project's `.claude/settings.json` hooks and `.mcp.json` servers without prompting (headless docs). **Verified:** Orca reads the repo's `.claude/` and `.codex/` (docs `/agents/hooks-memory`). **Verified:** a project `.codex/config.toml` loads only for trusted projects. Control: preflight diff of those paths against an allowlist, then `blocked:untrusted_config`. Use `--strict-mcp-config --mcp-config <rendered>` for Claude. |
| Risky agent flags | Locked deny-list. Claude: `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--permission-mode bypassPermissions`. Codex: `--dangerously-bypass-approvals-and-sandbox`, `-s danger-full-access`, `--dangerously-bypass-hook-trust`, `approval_policy=never` combined with a writable sandbox. The wrapper refuses before launch. |
| Over-broad tool permissions | Claude defaults to `--permission-mode default`, with `dontAsk` for unattended runs plus explicit `--allowedTools` such as `Bash(git diff *)`. Codex defaults to `-s workspace-write` with network off. Manual approval is the default for interactive runs. |
| MCP access to production data | No production MCP servers in agent profiles. MCP allowlist per profile; Claude `--disallowedTools "mcp__*"` by default. Jira MCP only later, read-only scope. |
| Credential leakage | Never read, print or commit credential stores (Keychain, `~/.codex/auth.json`, Orca `*.key`, `endpoint.env`, `*auth*.json`). No API keys in agent env. Redact before any audit write. |
| Unauthorized push or merge | Agents may push only `agent/*` branches and open PRs. Merge happens only on the host, with human approval. **Gap, below.** |
| Audit tampering or omission | Append-only JSONL in the workspace config repo; commits through the wrapper; Git history as the record. See the hash-chain criteria below. |
| Sensitive output in the audit | Store hashes, sizes and exit codes, not raw output. Never store raw transcripts. Redact token patterns and planted test secrets. |

## Merge protection: unresolved P0 gap

**Verified (2026-10-16):** for both `dvagapov/tools-configs-as-code` and `dvagapov/orca-workflow-fixture`:
- `gh api repos/<r>/branches/develop/protection` returns 404 "Branch not protected"
- `gh api repos/<r>/rulesets` returns `[]`
- the active `gh` user `dvagapov` has `repo` scope

So nothing currently stops an agent from merging or pushing directly to `develop`. Task 01 changed no settings.

Proposed ruleset for `develop`, applied by a human in backlog item B0:
- a pull request is required, with ≥ 1 approving review
- stale approvals are dismissed
- force-pushes and deletion are blocked
- no bypass actors, except an optional human admin

Identity problem: agents act through the human's `gh` login, so the host cannot tell their actions apart. Options, which need your decision:
- a separate bot account or fine-grained PAT for agents, with no admin role
- keep the human identity and rely on the wrapper's command allowlist. This is weaker, because self-approval rules don't apply.

Enforcement test (T2, run after B0):

| Step | Command | Expected |
|---|---|---|
| 1 | `git push origin HEAD:develop` from the agent identity | Non-zero exit; ruleset rejection text |
| 2 | `git push origin HEAD:agent/test-<id>` | Exit 0 |
| 3 | `gh pr create --base develop --head agent/test-<id> ...` | Exit 0; PR `OPEN` |
| 4 | `gh pr merge <n> --merge` without approval | Non-zero exit; `gh pr view <n> --json state` is still `OPEN` |
| 5 | `gh api repos/<r>/rulesets` | Non-empty; snapshot stored in the audit |

## Audit coverage

No completeness claim. Columns: what each source shows, and its gaps.

| Source | Observable | Evidence | Gaps |
|---|---|---|---|
| Orca orchestration CLI receipts (`run-show`, `task-list`, `worker-list`, `worker-show`, `gate-list`, `inbox`, `--json`) | Run, Task and Dispatch lifecycle; outcomes; gate decisions; liveness; `launch.requested` and `launch.effective` | Installed CLI help; `coordinator-loop.md` | Snapshot only, so the wrapper must poll or capture at each transition. Field schemas aren't versioned beyond `agent-context` `schemaVersion`. |
| `orca orchestration check --wait` deliveries | `worker_done`, `escalation`, `question` messages | CLI help | A message body is agent-written, so it is a claim, not evidence |
| `logs/main.trace.ndjson`, `logs/daemon.log` | Unknown | File exists (names only) | Format undocumented; not a contract; may hold sensitive data. **Do not ingest.** |
| Orca agent status hooks | working, waiting or done status | Docs `/agents/hooks-memory`; `orca agent hooks status` | Not an event log |
| Claude `-p --output-format stream-json --verbose` | `system/init` (`model`, tools, `mcp_servers`, `capabilities`); tool use; `permission_denied`; final `result` with cost and `permission_denials` | Headless docs | Only in `-p` mode. Interactive TUI sessions under Orca aren't captured unless hooks are installed. No effort field. |
| Claude hooks (PreToolUse and others; exit 2 blocks) | Per-tool-call events, if the framework renders them | Hooks docs | Must be framework-rendered. Repo hooks are untrusted. |
| Codex `exec --json` | `thread.started`, `turn.*`, `item.*`, `error`; token usage | Non-interactive docs | No model or effort reported; exit codes undocumented |
| Codex hooks | PreToolUse, PostToolUse, PermissionRequest and others | `codex features list` (hooks stable) | Same as Claude hooks |
| `git` and `gh` exit codes and state | Branch, commits, push result, PR state, ruleset snapshot | Local CLIs | — |
| Wrapper-captured actions | Merged config hash, rendered argv (redacted), preflight results, transitions, verification results | Proposed | Only what passes through the wrapper |

**Not observable today:**
- tool calls inside interactive Orca-launched TUI sessions without framework hooks
- the reasoning effort the provider actually served (both CLIs)
- the model actually served behind the local proxies
- proxy-side traffic
- actions taken outside the wrapper by a human or another agent in the same worktree

## Audit integrity decision

- **MVP:** one JSONL file per run under `audit/runs/<run_id>.jsonl` plus `audit/runs/<run_id>.manifest.yaml` in the workspace config repo. The wrapper commits them. Integrity comes from Git history and remote push. Signed commits are optional.
- **Hash chain: deferred.** Adopt it only if one of these becomes true:
  - multiple writers who don't trust each other share one audit repo
  - audit records serve compliance where history rewrites must be detectable without trusting the host
  - agents gain write access to the audit repo outside the wrapper
