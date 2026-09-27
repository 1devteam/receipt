# Receipt

Collect, preserve, normalize, and catalog `.py` receipts onto a **shelf**. Browse and search them. Selectively restack a closed Python dependency subset into an installable project.

Product CLI: **`receipt`**  
Pipeline tools: `collect` · `compile` · `produce` · `direct` · `pipeline`  
Local UI: **`receipt dashboard`** (`http://127.0.0.1:8787/`)

Legacy `insert` / `insertc` entry points still ship for old workflows; prefer `receipt`.

## Quick start

```bash
# 1. Collect a tree onto a shelf (empty shelves → collect first)
receipt collect ~/src/mytree -o ~/projects/catalogs/mytree

# or pull .py files from GitHub (public; private needs GITHUB_TOKEN / GH_TOKEN)
receipt collect https://github.com/owner/repo -o ~/projects/catalogs/repo
receipt collect github:owner/repo@main:src -o ~/projects/catalogs/repo
receipt collect owner/repo --ref v1.2.0 -o ~/projects/catalogs/repo

# refresh a GitHub shelf (same origin). existing catalog refuses without --update/--force
receipt sync -c ~/projects/catalogs/repo
receipt collect https://github.com/owner/repo -o ~/projects/catalogs/repo --update

# 2. Browse / search
receipt catalogs
receipt status -c ~/projects/catalogs/mytree
receipt list   -c ~/projects/catalogs/mytree -q Core
receipt find   ping -c ~/projects/catalogs/mytree
receipt show   CoreStatus.py -c ~/projects/catalogs/mytree

# 3. Plan dependency closure, then stack
receipt plan  CoreStatus.py -c ~/projects/catalogs/mytree
receipt stack CoreStatus.py --name spine -o ~/projects/compiled/spine

# Gaps (missing/ambiguous local deps) refuse stack unless --force
receipt stack Seed.py --name partial -o /tmp/partial --force

# 4. Dashboard (browse, inspect normalized source, collect, plan, stack)
receipt dashboard
# http://127.0.0.1:8787/
```

Defaults:

- Catalog: `RECEIPT_CATALOG`, else `~/projects/catalogs/evolved`
- Shelves root: `RECEIPT_CATALOGS` (default `~/projects/catalogs`)

If there is no catalog yet, create one with `receipt collect` (or the Collect form in the dashboard).

## GitHub source

`collect` TREE may be a local path **or** a GitHub spec. Receipt downloads a snapshot tarball, then onboard/catalogs it.

Accepted specs:

- `https://github.com/owner/repo`
- `https://github.com/owner/repo/tree/branch`
- `https://github.com/owner/repo/tree/branch/subdir`
- `https://github.com/owner/repo/blob/branch/path/to/file.py`
- `github:owner/repo@ref`
- `github:owner/repo@ref:src/pkg`
- `owner/repo` and `owner/repo@ref` (only if that path does not already exist locally)
- `--ref` overrides the ref in the spec (branch, tag, or SHA)

Private repos and higher API rate limits: set `GITHUB_TOKEN` or `GH_TOKEN`. Receipt does not vendor git.

The catalog records `source` (`kind=github`, owner, repo, ref, **sha**, url). Collect resolves the commit SHA and pins blob URLs to that SHA, not the branch name.

Existing catalog directories refuse a second collect unless:

- `--update` — re-fetch the **same** origin, replace changed receipts, prune removed ones, report `diff` (`added` / `removed` / `changed` / `unchanged`)
- `--force` — replace the catalog (or, with `--update`, switch origin)

`receipt sync` re-fetches from the catalog's stored GitHub `source` (optional `--ref` to move the pin). Local catalogs have no GitHub source; use `collect TREE -o CATALOG --update`.

The normalized shelf copy is the compile source of truth. The exact original bytes are preserved separately as provenance evidence.

## Onboard and provenance model

When a `.py` is collected onto the shelf:

| Action | What happens |
|---|---|
| **Preserve raw source** | Exact original bytes are stored under `raw/` and keyed by `source_sha256`. |
| **Normalize compile source** | Python is parsed/unparsed; `__main__` launchers and Receipt/Insert ownership metadata are removed when present. |
| **Record transforms** | Each receipt records `source_sha256`, `normalized_sha256`, and the exact normalization transform names applied. |
| **Extract to sidecars** | **contracts** (classes/methods/functions) and **dependencies** (local / external / relative / stdlib). |
| **Keep in normalized `.py`** | APIs and imports remain in the compile source; contracts are not deleted from source. |

`sha256` remains an alias for the original source-content SHA-256 for compatibility. `copy` points at the normalized compile source.

Catalog layout:

```text
catalog/
  receipts.json
  index.json
  raw/<source-sha>.py
  normalized/<normalized-sha>.py
  contracts/<source-sha>.json
  dependencies/<source-sha>.json
```

This split is intentional: raw source proves exactly what Receipt collected; normalized source proves exactly what Receipt compiles.

## Plan / stack

- **`receipt plan`** — resolve seed units and close along extracted absolute-local and relative Python dependency edges. Reports `missing_local` / `ambiguous_local`; does not invent glue.
- Nested imports participate in dependency discovery.
- Conventional `src/` and `lib/` source roots are recognized when classifying absolute imports.
- **`receipt stack`** — plan → compile → produce → director check. Refuses unresolved local deps unless `--force`.
- Produced projects include an installable `pyproject.toml` (`build-system` + `packages.find` where `src`).

## Dashboard

`receipt dashboard` serves a local shelf UI:

- Catalog picker, status, symbol find, receipt list with multi-select
- Inspect contracts/deps and normalized shelf **source** preview (`/api/copy`)
- Collect form (`/api/collect`) then refresh catalogs
- Plan / stack with optional **force**
- Surfaces plan gaps and `compile_errors`

The dashboard is a local developer interface. Do not expose it as a public service without an execution sandbox and a stricter filesystem boundary.

## Pipeline tools

```bash
collect TREE -o ~/projects/catalogs/evolved
collect find ping -c ~/projects/catalogs/evolved

compile ~/projects/catalogs/evolved/receipts.json --name evolved -o /tmp/compile-out
produce /tmp/compile-out -o ~/projects/compiled/evolved
direct check ~/projects/compiled/evolved
direct call  ~/projects/compiled/evolved i_evolved.CoreStatus CoreStatus.ping VoiceSynth

python -m pipeline build TREE --name evolved --out ~/projects/compiled/evolved
python -m pipeline build https://github.com/owner/repo --name evolved --out ~/projects/compiled/evolved
```

| Program | Job |
|---|---|
| `collect` | receipts / catalog only |
| `compile` | rewrite + contracts + deps (staging dir) |
| `produce` | print a project to disk |
| `direct` | first-start roster, then calls |
| `pipeline` | one-shot collect → compile → produce → check |

Same steps are also available as `receipt collect|compile|produce|direct|pipeline …`.

## Limits

- **Source-to-source.** No binary. Stack = Python package + maps.
- Broken Python fails that unit at compile; recorded in `errors` / `compile_errors`.
- External imports are observed module names, not proven Python distribution names. Producer currently writes those roots to `requirements.txt` as a best-effort manifest.
- Side effects on import still happen; director isolates imports in subprocesses.
- The pipeline does not invent glue between files that never imported each other.
- Relative imports are preserved in compiled source after their dependency edges participate in planning.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success / ready |
| `1` | usage or input error |
| `2` | empty collect, compile partial errors, plan gaps, or local graph broken |
| `3` | director/pipeline: imports failing (`ready` false) |

## Layout

```text
receipt/
  receipt_cli/   # product CLI + shelf + stack + dashboard
  collector/     # scan, preserve, normalize, catalog, find
  compiler/      # owned-module rewrite
  producer/      # project printer
  director/      # check + call
  pipeline/      # one-shot glue
  common/        # io, names, refuse
  insert/        # legacy house (demoted)
  insertc/       # legacy companion compiler (demoted)
```

## Legacy

`insert` and `insertc` remain as console scripts for old vault/host workflows. They print a one-line stderr notice pointing at `receipt`. Prefer the shelf + stack model above. The `vault/` tree is a local sample/legacy house and is gitignored for day-to-day work.
