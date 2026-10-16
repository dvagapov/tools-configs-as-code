# Config Contracts (Proposed)

These are framework formats, not native Orca, Claude Code or Codex formats. Only flags and keys marked **Verified** exist in the installed CLIs (see [task-01-report.md](../discovery/task-01-report.md)). The examples are illustrative, and the JSON Schemas come later (backlog item B3).

## Precedence

- Layers merge in order: `framework/defaults.yaml` → `<workspace>/workspace.yaml` → `<repo>/.cac/repo-policy.yaml`.
- Merge rules:
  - maps merge deeply
  - scalars are replaced by the later layer
  - lists are replaced, unless the schema marks them `x-merge: append`
- Paths under `locked:` are framework-only. Overriding one is a validation error.

## Framework defaults and pins

```yaml
# framework/defaults.yaml
schemaVersion: 1
pins:                        # drift check before every run
  orca: "1.4.197"            # `orca --version`
  orcaAgentContextSchema: 1  # `orca agent-context --json` .schemaVersion
  claude: "2.1.299"          # `claude --version`
  codex: "0.163.0"           # `codex --version`
  gh: "2.92.0"
runtime:
  autostart: false           # never run `orca open` implicitly
locked:
  merge.byAgent: forbidden
  redaction.enabled: true
  agentFlags.deny:
    claude: ["--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--permission-mode=bypassPermissions"]
    codex: ["--dangerously-bypass-approvals-and-sandbox", "--sandbox=danger-full-access", "--dangerously-bypass-hook-trust"]
  verification.manifestRequired: true
  review.afterRemediation: mandatory
```

## Agent profiles

```yaml
# framework/agents/profiles.yaml
profiles:
  planner:
    agent: claude
    model: opus            # Verified alias; served model is unverified
    effort: high           # Verified values: low|medium|high|xhigh|max
    permissionMode: plan   # Verified value
  implementer:
    agent: claude
    model: sonnet
    effort: medium
    permissionMode: default
    allowedTools: ["Read", "Edit", "Bash(git diff *)", "Bash(git status *)", "Bash(git commit *)"]
  reviewer:
    agent: codex
    model: null            # unverified default; set explicitly once proven
    effort: high           # Verified key: model_reasoning_effort
    sandbox: read-only     # Verified values: read-only|workspace-write|danger-full-access
  verifier:
    agent: codex
    sandbox: workspace-write
  git-ops:
    agent: codex
    sandbox: workspace-write
    allowedCommands: ["git push origin agent/*", "gh pr create", "gh pr view"]
launch:
  via: orca-worker-start   # orca orchestration worker-start --agent --model --effort
  recordEffective: true    # store launch.requested and launch.effective
```

## Workspace manifest

```yaml
# <workspace-config>/workspace.yaml
schemaVersion: 1
workspace: acme
frameworkRef: tools-configs-as-code@v0.1.0
wiki:
  repo: git@github.com:dvagapov/acme-wiki.git
  branch: main
repos:
  - name: orca-workflow-fixture
    url: git@github.com:dvagapov/orca-workflow-fixture.git
    host: github           # github → gh; gitlab → glab
overrides:
  workflow.remediation.maxCycles: 3
audit:
  path: audit/runs
```

## Repo policy

```yaml
# <app-repo>/.cac/repo-policy.yaml
schemaVersion: 1
baseBranch: develop
branchPattern: "agent/{task_id}-{slug}"
pr:
  template: .github/pull_request_template.md
  draft: true
  labels: ["agent"]
verification:
  manifest: .cac/verify.yaml
trustedAgentConfig:        # repo-supplied agent config the wrapper allows
  - CLAUDE.md
  - AGENTS.md
```

## Verification manifest

```yaml
# <app-repo>/.cac/verify.yaml
schemaVersion: 1
steps:
  - id: unit
    run: ["npm", "test"]
    expectExit: 0
    timeoutSec: 600
    artifacts: ["coverage/coverage-summary.json"]
  - id: lint
    run: ["npm", "run", "lint"]
    expectExit: 0
```

- The wrapper runs each step and checks the exit code and that each artifact exists.
- Agent output never decides pass/fail.

## Audit event and run manifest

```jsonl
{"v":1,"ts":"2026-10-16T12:00:00Z","run":"r_…","state":"verify_run","event":"step_result","step":"unit","exit":1,"expected":0,"stdoutSha256":"…","bytes":5321,"redactions":0}
{"v":1,"ts":"…","run":"r_…","event":"transition","from":"verify_run","to":"remediate","reason":"exit_mismatch"}
```

```yaml
# audit/runs/<run_id>.manifest.yaml
run: r_…
workspace: acme
repo: orca-workflow-fixture
configSha256: "…"
pins: {orca: "1.4.197", claude: "2.1.299", codex: "0.163.0"}
orca: {runId: "…", dispatches: ["…"]}
launches:
  - profile: planner
    requested: {model: opus, effort: high}
    effective: {model: opus, effort: high}   # from Orca launch.effective
    servedModel: null                        # from Claude system/init when captured
result: {final: await_merge, pr: "https://github.com/…/pull/1"}
redaction: {patterns: 12, hits: 0}
```

What is never stored:
- raw transcripts
- unredacted stdout or stderr
- environment values
- credential paths' contents

## Workspace wiki

Based on the Karpathy LLM Wiki: raw sources are immutable, the wiki layer is owned by LLMs, and a schema file sets the rules.

```text
<wiki-repo>/
  AGENTS.md        # wiki schema and ops (ingest/query/lint)
  raw/             # immutable sources; raw/assets/
  pages/           # LLM-owned pages
  index.md         # catalog: link + one-line summary + metadata
  log.md           # append-only: "## [YYYY-MM-DD] <op> | <title>"
```

Page front matter:

```yaml
---
title: Checkout service
sources:
  - repo: orca-workflow-fixture
    commit: 1a2b3c4
    path: src/checkout.ts
  - raw: raw/2026-10-16-design-notes.md
updated: 2026-10-16
run: r_…
---
```

**Sync** (conflict-safe):
1. `git pull --rebase`.
2. Edit pages and append to `log.md`.
3. Commit.
4. `git push`. If rejected, re-run the rebase and retry, up to 3 times. After that, set `blocked:wiki_conflict`.
5. Resolve `log.md` conflicts by union, keeping entries ordered by timestamp. Never let an agent auto-resolve page conflicts.

**Lint** (proposed `wiki lint`):
- orphan pages
- missing index entries
- pages without `sources`
- stale `commit` references
- malformed log headers
