# {{workspace}} project repo

Knowledge and config for the `{{workspace}}` project. App repos are cloned into `repos/` (not committed).

## Rules
- `wiki/raw/` holds external sources. Never edit them; add new ones as new files. Run the secret scan before committing.
- `wiki/pages/` is maintained by agents. Every page lists its sources. Append every change to `wiki/log.md` as `## [YYYY-MM-DD] <op> | <title>`.
- `audit/summaries/` holds reviewed summaries only. Raw audit data is never committed.
- `incidents/` documents alerts and how to reach observability data. Names and endpoints only, never credentials.
- Do not edit `workspace.yaml` during an agent run. Agents never merge.
