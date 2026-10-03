from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.io import read_json
from receipt_stock.bootstrap import bootstrap_stock
from receipt_stock.build import StockBuildError, plan_stock, stack_stock
from receipt_stock.coverage import build_stock_coverage
from receipt_stock.manifest import StockManifestError, load_bootstrap_manifest
from receipt_stock.query import StockQueryError, find_units, load_unit_index


def _print(data) -> None:
    print(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="receipt-stock",
        description="Receipt curated stock bootstrap, inventory, discovery and source-safe stacking",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_manifest = sub.add_parser("manifest", help="show the validated bootstrap manifest")
    p_manifest.add_argument("--manifest", default=None)

    p_bootstrap = sub.add_parser("bootstrap", help="materialize pinned curated stock catalogs")
    p_bootstrap.add_argument("-o", "--out", required=True, help="stock root directory")
    p_bootstrap.add_argument("--manifest", default=None, help="override bootstrap manifest")
    p_bootstrap.add_argument("--force", action="store_true", help="replace existing source catalogs")

    p_status = sub.add_parser("status", help="show a materialized stock inventory")
    p_status.add_argument("root", help="stock root containing stock-index.v1.json")

    p_coverage = sub.add_parser(
        "coverage",
        help="show which observed external package roots are already represented by other stock packs",
    )
    p_coverage.add_argument("root", help="materialized stock root")

    p_find = sub.add_parser("find", help="search admitted stock units across all source catalogs")
    p_find.add_argument("root", help="materialized stock root")
    p_find.add_argument("query", nargs="?", default=None, help="path, symbol, tag, dependency or effect text")
    p_find.add_argument("--capability", action="append", default=[], help="required capability tag; repeat to require multiple tags")
    p_find.add_argument("--any-capability", action="store_true", help="match any requested capability instead of requiring all")
    p_find.add_argument("--source", default=None, help="bootstrap source id")
    p_find.add_argument("--decision", choices=["accepted", "constrained", "rejected"], default=None)
    p_find.add_argument("--external", default=None, help="filter by observed external dependency")
    p_find.add_argument("--limit", type=int, default=50, help="maximum matches (default 50)")

    p_units = sub.add_parser("units", help="show the federated stock-unit index summary")
    p_units.add_argument("root", help="materialized stock root")

    p_plan = sub.add_parser("plan", help="map explicit federated stock unit ids into the existing Receipt stack plan")
    p_plan.add_argument("root", help="materialized stock root")
    p_plan.add_argument("unit_ids", nargs="+", help="exact stock unit id or unique id prefix")

    p_stack = sub.add_parser("stack", help="compile explicit stock unit ids through the existing Receipt stack/compiler path")
    p_stack.add_argument("root", help="materialized stock root")
    p_stack.add_argument("unit_ids", nargs="+", help="exact stock unit id or unique id prefix")
    p_stack.add_argument("--name", required=True, help="batch/package name")
    p_stack.add_argument("-o", "--out", required=True, help="output project directory")
    p_stack.add_argument("--work", default=None, help="keep staging directory")
    p_stack.add_argument("--check", action="store_true", help="explicitly run Director import checks after build")
    p_stack.add_argument("--force", action="store_true", help="allow existing stack force boundary")

    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.cmd == "manifest":
            _print(load_bootstrap_manifest(args.manifest))
            return 0
        if args.cmd == "bootstrap":
            result = bootstrap_stock(Path(args.out), manifest_path=Path(args.manifest) if args.manifest else None, force=args.force)
            _print(result)
            return 0 if result.get("totals", {}).get("files") else 2
        if args.cmd == "status":
            root = Path(args.root).expanduser().resolve()
            _print(read_json(root / "stock-index.v1.json"))
            return 0
        if args.cmd == "coverage":
            _print(build_stock_coverage(args.root))
            return 0
        if args.cmd == "units":
            data = load_unit_index(args.root)
            _print({"schema": data.get("schema"), "counts": data.get("counts") or {}, "fingerprint": data.get("fingerprint"), "grants_execution_authority": False})
            return 0
        if args.cmd == "find":
            hits = find_units(args.root, query=args.query, capabilities=args.capability, require_all_capabilities=not args.any_capability, source_id=args.source, decision=args.decision, external=args.external, limit=args.limit)
            _print({"root": str(Path(args.root).expanduser().resolve()), "query": args.query, "capabilities": args.capability, "count": len(hits), "units": hits, "grants_execution_authority": False})
            return 0 if hits else 1
        if args.cmd == "plan":
            result = plan_stock(args.root, args.unit_ids)
            _print(result)
            plan = result.get("plan") or {}
            return 2 if plan.get("missing_local") or plan.get("ambiguous_local") else 0
        if args.cmd == "stack":
            result = stack_stock(args.root, args.unit_ids, name=args.name, out=args.out, work=args.work, check=args.check, force=args.force)
            _print(result)
            if result.get("compile_errors") or result.get("compiler_contract_violations"):
                return 2
            roster = result.get("roster") or {}
            if roster and (not roster.get("local_graph_ok") or not roster.get("ready")):
                return 3
            return 0
    except (StockManifestError, StockQueryError, StockBuildError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1
