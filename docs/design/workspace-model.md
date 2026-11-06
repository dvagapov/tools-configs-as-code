# Workspace model (decided 2026-11-06)

Supersedes the layering table in the Task 01 report where they differ. Decisions are the owner's; **Proposed** and **Open** mark what is not decided.

## Shape

- `tools-configs-as-code` is the **framework and template**: code, schemas, defaults, profiles. It never holds project data.
- Each **Project** (workspace) has one **private project repo**, created from this template. It is the single home of project knowledge and config. App repos (Website, Ops, ...) stay separate and hold code only, plus `.cac/repo-policy.yaml` and `.cac/verify.yaml`.
- The project repo pins the framework with `frameworkRef`. Framework upgrades are a version bump, not a branch merge.

```text
<project-repo>/
  workspace.yaml        # repo list (GitHub/GitLab), overrides, frameworkRef, repo rules to apply
  AGENTS.md             # schema and rules for the wiki and this repo
  wiki/
    raw/<source>/       # unchanged external sources: slack, telegram, pdf, doc, ...
    pages/              # LLM-owned pages: business logic + implementation
    index.md  log.md
  audit/
    summaries/          # short reviewed summaries, one per change (committed)
  incidents/
    alerts/             # what each alert means, owner, runbook link
    observability.md    # which MCP servers / dashboards give observability data (names and endpoints only)
    postmortems/
```

- Raw audit data is **not** in the repo (see Audit). A `.gitignore` for the local audit directory ships with the template.

## Why one repo

The project repo is the context an LLM is given for: new tickets, investigations and incidents, bug fix or revert procedure, security audit questions, project questions, and generating follow-up tasks (improvements). Wiki explains what and why, audit summaries show what agents changed and what was flagged, incidents show how it behaves in production.

## Wiki

- One wiki per project, shared by every repo in it (e.g. Website + Ops with Terraform and Ansible, and how they deploy together). It keeps business logic and implementation notes together.
- Raw data is dropped **manually** into `wiki/raw/<source>/`; an agent ingests it. Importers for chat tools are a later task.
  - Raw data is stored in this private repo, so a **secret scan runs before commit**. The audit redactor does not cover `raw/`.
- Sync and backup: changes go to a work branch and a **PR; a human merges**. Agents never merge. Teammates' changes sync through the same PRs.
  - Conflicts on page content are surfaced for a human, never auto-resolved.
  - **Open:** may solo use push straight to the main branch through a config switch?

## Audit

- Raw audit data (how the LLMs worked) stays **local**, gitignored, outside any repo. It is never committed.
- **Pre-commit audit review:** before a commit, an LLM reads the run's audit records and writes one **short summary file**. That file is committed to `audit/summaries/` in the project repo, in the same PR flow as wiki changes. A run that touches several app repos produces one summary.
  - Summary content: what the agents did, and highlighted issues: security (denied actions, deny-listed flags, merge attempts, redaction hits), **clickOps** (resources created or changed outside code), other anomalies.
  - The summary carries no raw output, only counts, step ids and finding text.
- Guardrails (**Proposed**):
  - The wrapper runs deterministic checks first (denials, redaction hits, blocked states, failed steps) and gives them to the LLM as facts. The LLM interprets; it does not decide what counts as a violation.
  - The summary goes through the redactor and the secret scan before it is written. LLM output is untrusted.
  - The reviewer is a different agent than the one that did the work (e.g. Codex reviews Claude's run).
  - The reviewer gets audit text as quoted data in a read-only sandbox with no tools (audit text can carry prompt injection from repo content).
  - The summary is an aid, not evidence. Local files can be edited, so tamper evidence is still missing.
- **clickOps limit:** the audit only sees what the wrapper and agents did. Changes made by hand in a console, or by tools outside a run, are invisible to it. Real detection needs another source (e.g. `terraform plan` drift output, cloud or `gh api` state) fed into the same review.
- **Open:** should a high-severity finding (deny-listed flag, merge attempt) block the commit until a human acknowledges it? Proposed default: yes.
- Limit for context use: the committed summaries are what the LLM can read later. Questions that need detail from a past run cannot be answered from them once the local raw files are gone.

## Incidents

- `incidents/` holds docs about alerts and the **MCP servers or tools that give access to observability data** (logs, metrics, traces).
- The repo stores names, endpoints and how to use them, **never credentials**. Credentials stay in the keychain or environment, outside the repo.
- Later: a daily summary of audit data dropped into `incidents/`.

## Agents and tools

- Orca-supervised workers: Claude and Codex.
- Gemini CLI: a **direct CLI step launched by the wrapper**, outside Orca (Orca 1.4.197 lists only Claude, Codex and Cursor). It needs its own profile, pin, deny-listed flags and audit capture.
- Changing agents means changing profiles; the profile schema's `agent` enum grows per verified tool.

## Backlog

| ID | Item |
|---|---|
| W1 | `cac project init`: create the project repo from the template (layout above, `.gitignore`, `workspace.yaml`) |
| W2 | `cac project sync`: clone or pull the listed app repos into the project directory |
| W3 | Apply per-project GitHub/GitLab rules via `gh api` (depends on B0 and admin approval) |
| W4 | Wiki template, secret scan for `raw/`, ingest flow (replaces and extends B8) |
| W5 | PR flow for wiki and audit-summary changes; human merge |
| W6 | Gemini profile and direct-launch adapter |
| W7 | Local audit directory convention |
| W8 | Pre-commit audit review: deterministic checks, LLM summary, redact and secret-scan, write to `audit/summaries/` |
| W9 | Drift source for clickOps (e.g. `terraform plan`, `gh api` state) feeding W8 |
| W10 | `incidents/` template and observability-MCP doc format; daily audit summary |
