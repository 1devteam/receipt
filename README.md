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

# 3. Ask Receipt's internal G.R.A.F.T.+ for blast radius + proof surfaces
receipt-graft ~/projects/catalogs/mytree --impact CoreStatus.py

# 4. Plan dependency closure, then stack
receipt plan  CoreStatus.py -c ~/projects/catalogs/mytree
receipt stack CoreStatus.py --name spine -o ~/projects/compiled/spine

# Gaps (missing/ambiguous local deps) refuse stack unless --force
receipt stack Seed.py --name partial -o /tmp/partial --force

# Runtime import checking is an explicit trust transition
receipt stack CoreStatus.py --name spine-checked -o ~/projects/compiled/spine-checked --check

# 5. Dashboard (browse, inspect normalized source, collect, plan, stack)
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
| **Extract to sidecars** | **contracts**, **dependencies**, and **topology** (bindings, calls, inheritance, dynamic imports, env/effect surfaces). |
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
  topology/<source-sha>.json
  graft/stock-graph.v1.json
  graft/impact.v1.json        # when impact analysis is requested
```

This split is intentional: raw source proves exactly what Receipt collected; normalized source proves exactly what Receipt compiles; sidecars and G.R.A.F.T.+ artifacts expose architecture without becoming execution authority.

## Internal G.R.A.F.T.+

Receipt's internal G.R.A.F.T.+ is a deterministic, source-grounded reconstruction of the stock. It exposes module identity, contracts, import/call/inheritance relationships, dynamic boundaries, environment reads, external dependencies, effect surfaces, unresolved relationships, and adjacency while leaving the final application outcome open.

```bash
# rebuild the current stock graph
receipt-graft ~/projects/catalogs/mytree

# derive a bidirectional blast-radius/proof slice from a rel path, module, class, or function seed
receipt-graft ~/projects/catalogs/mytree --impact compiler/compile.py
receipt-graft ~/projects/catalogs/mytree --impact compiler.compile

# multiple seeds describe one candidate change/assembly surface
receipt-graft ~/projects/catalogs/mytree --impact compiler.compile producer.produce
```

The impact artifact reports direct and transitive upstream/downstream reachability, relationship kinds, unresolved boundaries, external dependencies, environment/effect surfaces, and candidate test files. Reachability is evidence of possible impact, **not** an instruction that every reachable file must change. The report is content-fingerprinted and carries `grants_execution_authority=false`, `implements_plan=false`, and `change_authority=not-determined`.

Receipt preserves the external G.R.A.F.T.+ identity/evidence bridge so a larger future build can correlate Receipt stock evidence with the universal graph without merging responsibilities or authority.

## Plan / stack

- **`receipt plan`** — resolve seed units and close along extracted absolute-local and relative Python dependency edges. Reports `missing_local` / `ambiguous_local`; does not invent glue.
- Nested imports participate in dependency discovery.
- Conventional `src/` and `lib/` source roots are recognized when classifying absolute imports.
- **`receipt stack`** — plan → compile → produce. Refuses unresolved local deps unless `--force`.
- `--check` explicitly asks the director to import/check produced code after build.
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
| `collect` | receipts / catalog + internal stock graph |
| `compile` | rewrite + contracts + deps (staging dir) |
| `produce` | print a project to disk |
| `direct` | explicit check + calls |
| `pipeline` | one-shot collect → graph → compile → produce; check only when requested |

Same steps are also available as `receipt collect|compile|produce|direct|pipeline …`.

## Limits

- **Source-to-source.** No binary. Stack = Python package + maps.
- Broken Python fails that unit at compile; recorded in `errors` / `compile_errors`.
- External imports are observed module names, not proven Python distribution names. Producer currently writes those roots to `requirements.txt` as a best-effort manifest.
- Side effects on import can occur when explicit runtime checking is requested; director isolates imports in subprocesses.
- The pipeline does not invent glue between files that never imported each other.
- Relative imports are preserved in compiled source after their dependency edges participate in planning.
- Static G.R.A.F.T.+ relationships are evidence-backed but cannot prove runtime-only behavior unless runtime evidence is later attached.

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
  collector/     # scan, preserve, normalize, catalog, topology extraction
  receipt_graft/ # internal stock graph + impact/proof reconstruction
  compiler/      # owned-module rewrite
  producer/      # project printer
  director/      # explicit check + call
  pipeline/      # one-shot glue
  common/        # io, names, refuse
  insert/        # legacy house (demoted)
  insertc/       # legacy companion compiler (demoted)
```

## Legacy

`insert` and `insertc` remain as console scripts for old vault/host workflows. They print a one-line stderr notice pointing at `receipt`. Prefer the shelf + stack model above. The `vault/` tree is a local sample/legacy house and is gitignored for day-to-day work.
