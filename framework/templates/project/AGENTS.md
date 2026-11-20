# {{workspace}} project repo

Knowledge and config for the `{{workspace}}` project. App repos are cloned into `repos/` (not committed).

## Rules
- `wiki/raw/` holds external sources. Never edit them; add new ones as new files. Run the secret scan before committing.
- `wiki/pages/` is maintained by agents. Every page lists its sources. Append every change to `wiki/log.md` as `## [YYYY-MM-DD] <op> | <title>`.
- `audit/summaries/` holds reviewed summaries only. Raw audit data is never committed.
- `incidents/` documents alerts and how to reach observability data. Names and endpoints only, never credentials.
- Do not edit `workspace.yaml` during an agent run. Agents never merge.

## Ingesting a raw source
1. Add it with `cac wiki add-raw <source> <file>` (secret scan, no overwrite, logged). Do not copy files into `wiki/raw/` by hand.
2. Create or update pages in `wiki/pages/`. Each page starts with front matter:
   ```
   ---
   title: <page title>
   sources:
     - raw: wiki/raw/<source>/<file>
   updated: YYYY-MM-DD
   ---
   ```
3. List every page in `wiki/index.md` as `[title](pages/<file>.md) - one line`.
4. Append to `wiki/log.md`.
5. Run `cac wiki lint` and `cac scan`; fix everything they report before committing.
