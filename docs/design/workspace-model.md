# Workspace model (decided 2026-11-06)

Supersedes the layering table in the Task 01 report where they differ. Decisions are the owner's; items marked **Open** are not decided.

## Shape

- `tools-configs-as-code` is the **framework and template**. It holds code, schemas, defaults and profiles. It never holds project data.
- Each **workspace** is its own **private repo created from this template**. It holds:
  - `workspace.yaml`: the repo list (GitHub or GitLab), overrides, and a `frameworkRef` that pins the framework version
  - the workspace's GitHub or GitLab rules, as config to apply (branch names, rulesets)
  - local-only audit settings
- Framework upgrades are a version bump of `frameworkRef`, not a branch merge.
- Each app repo keeps `.cac/repo-policy.yaml` and `.cac/verify.yaml`, as before.

## Wiki

- One wiki per workspace, in its **own private git repo**, shared by every repo in the workspace (e.g. Website + Ops). It keeps business logic and implementation notes together.
- Layout: `raw/` (unchanged sources), `pages/` (LLM-owned), `index.md`, `log.md`, `AGENTS.md`.
- `raw/<source>/` subfolders hold external material: chat exports (Slack, Telegram), files (PDF, DOC), and similar.
  - Raw data is dropped **manually**; an agent ingests it. Importers for chat tools are a later task.
  - Raw data is stored in the private wiki repo, so a **secret scan must run before commit**. The audit redactor does not cover `raw/`.
- Backup and team sync: `wiki_update` pushes a work branch and opens a **PR; a human merges**. Agents never merge. This replaces the earlier "pull --rebase and push to main" step.
  - A merge conflict is surfaced for a human, never auto-resolved on page content.
  - Solo use may still push directly while there is one user (**Open**: whether to allow that as a config switch).

## Audit

- Audit data (how the LLMs worked) stays **local**, gitignored, outside any repo.
- Consequence: no Git-history integrity record. Acceptable for a single user; revisit if audit evidence is ever needed by others.
- Later: a daily summary (analyser tool or LLM) of redacted data, pushed to the incident-management repo.

## Agents and tools

- Orca-supervised workers: Claude and Codex.
- Gemini CLI: a **direct CLI step launched by the wrapper**, outside Orca, because Orca 1.4.197 lists only Claude, Codex and Cursor. It needs its own profile, pin, deny-listed flags and audit capture.
- Changing agents means changing profiles; the profile schema's `agent` enum grows per verified tool.

## Backlog added by these decisions

| ID | Item |
|---|---|
| W1 | `cac workspace init`: create the workspace repo from the template, write `workspace.yaml` |
| W2 | `cac workspace sync`: clone or pull the listed repos into the project directory |
| W3 | Apply per-workspace GitHub/GitLab rules via `gh api` (depends on B0 and admin approval) |
| W4 | Wiki repo template, secret scan for `raw/`, ingest flow (this replaces and extends B8) |
| W5 | `wiki_update` as a PR flow; human merge |
| W6 | Gemini profile and direct-launch adapter |
| W7 | Local audit directory convention and daily-summary export |
