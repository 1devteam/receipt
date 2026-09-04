# Changelog

## 0.3.0 — 2026-09-04

### Added
- `collect` accepts GitHub specs: repo URL, `/tree` / `/blob` paths, `github:owner/repo@ref`, `owner/repo`
- `--ref` on `collect` and `pipeline build` to pin branch / tag / SHA
- Dashboard Collect form accepts GitHub URLs
- Catalog `source` metadata and blob-URL `abs` for GitHub origins
- `GITHUB_TOKEN` / `GH_TOKEN` for private repos and rate limits

## 0.2.0 — 2026-08-27

### Added
- `receipt` product CLI: shelf browse (`catalogs`, `status`, `list`, `find`, `show`)
- Selective restack: `receipt plan` / `receipt stack` (local-dep closure only)
- Local dashboard (`receipt dashboard`) with browse, inspect, collect, plan, stack
- Dashboard APIs: `/api/copy`, `/api/collect`; stack `force` flag
- Shelf `read_copy` for source preview
- Producer emits installable `pyproject.toml` with `[build-system]` and `packages.find` (`where = ["src"]`)

### Changed
- `stack(..., force=False)` refuses missing/ambiguous local deps unless `force` / `--force`
- README rewritten around shelf-first workflow and dashboard
- Layout docs include `receipt_cli`; legacy `insert` / `insertc` / `vault` demoted

### Notes
- Legacy `insert` / `insertc` CLI entry points print a soft stderr warning pointing at `receipt`
