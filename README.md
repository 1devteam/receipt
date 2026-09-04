# Receipt

Collect, strip, and catalog `.py` receipts onto a **shelf**. Browse and search them. Selectively restack a closed local-dep subset into an installable project.

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

# 2. Browse / search
receipt catalogs
receipt status -c ~/projects/catalogs/mytree
receipt list   -c ~/projects/catalogs/mytree -q Core
receipt find   ping -c ~/projects/catalogs/mytree
receipt show   CoreStatus.py -c ~/projects/catalogs/mytree

# 3. Plan local-dep closure, then stack
receipt plan  CoreStatus.py -c ~/projects/catalogs/mytree
receipt stack CoreStatus.py --name spine -o ~/projects/compiled/spine

# Gaps (missing/ambiguous local deps) refuse stack unless --force
receipt stack Seed.py --name partial -o /tmp/partial --force

# 4. Dashboard (browse, inspect source, collect, plan, stack)
receipt dashboard
# http://127.0.0.1:8787/
```

Defaults:

- Catalog: `RECEIPT_CATALOG`, else `~/projects/catalogs/evolved`
- Shelves root: `RECEIPT_CATALOGS` (default `~/projects/catalogs`)

If there is no catalog yet, create one with `receipt collect` (or the Collect form in the dashboard).

## GitHub source

`collect` TREE may be a local path **or** a GitHub spec. Receipt downloads a snapshot tarball, then onboard/strip/catalog as usual.

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

The catalog records `source` (`kind=github`, owner, repo, ref, url). Each receipt `abs` is the GitHub blob URL. Shelf copies are still the compile source of truth.

## Onboard model

When a `.py` is collected onto the shelf:

| Action | What happens |
|---|---|
| **Strip from shelf copy** | `__main__` launchers, ownership stamps (`INSERT_*` / `RECEIPT_*`), ownership headers |
| **Extract to sidecars** | **contracts** (classes/methods/functions) and **dependencies** (local / external / relative / stdlib) |
| **Keep in the `.py`** | APIs and imports — contracts are not deleted from source |

Catalog layout:

```
catalog/
  receipts.json
  index.json
  copies/<sha>.py
  contracts/<sha>.json
  dependencies/<sha>.json
```

## Plan / stack

- **`receipt plan`** — resolve seed units and close along *extracted* local dependency edges only. Reports `missing_local` / `ambiguous_local`; does not invent glue.
- **`receipt stack`** — plan → compile → produce → director check. Refuses unresolved local deps unless `--force`.
- Produced projects include an installable `pyproject.toml` (`build-system` + `packages.find` where `src`).

## Dashboard

`receipt dashboard` serves a local shelf UI:

- Catalog picker, status, symbol find, receipt list with multi-select
- Inspect contracts/deps and shelf **source** preview (`/api/copy`)
- Collect form (`/api/collect`) then refresh catalogs
- Plan / stack with optional **force**
- Surfaces plan gaps and `compile_errors`

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
- External libs are named, not vendored. Producer writes `requirements.txt`.
- Side effects on import still happen; director isolates imports in subprocesses.
- The pipeline does not invent glue between files that never imported each other.
- Relative imports (`from .foo import bar`) are left untouched and recorded as compile warnings.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success / ready |
| `1` | usage or input error |
| `2` | empty collect, compile partial errors, plan gaps, or local graph broken |
| `3` | director/pipeline: imports failing (`ready` false) |

## Layout

```
receipt/
  receipt_cli/   # product CLI + shelf + stack + dashboard
  collector/     # scan, strip, catalog, find
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
