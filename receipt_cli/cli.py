from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from receipt_cli import __version__
from receipt_cli.shelf import (
    DEFAULT_CATALOGS,
    ShelfError,
    catalog_summary,
    default_catalog,
    list_catalogs,
    list_receipts,
    search_symbols,
    show_receipt,
)
from receipt_cli.stack import StackError, plan as stack_plan, stack as stack_build


def _print(data) -> None:
    print(json.dumps(data, indent=2))


def _add_catalog_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-c",
        "--catalog",
        default=None,
        help="catalog directory (else RECEIPT_CATALOG or ~/projects/catalogs/evolved)",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="receipt",
        description="Receipt CLI — browse and search py receipt shelves",
        epilog=(
            "Shelf commands are first-class. Local UI: receipt dashboard. "
            "Build steps via collect/compile/produce/direct or receipt stack. "
            "collect TREE may be a local path or a GitHub spec."
        ),
    )
    p.add_argument("--version", action="version", version=f"receipt {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_cats = sub.add_parser("catalogs", help="list catalogs under the shelves root")
    p_cats.add_argument(
        "--root",
        default=None,
        help=f"catalogs root (default: {DEFAULT_CATALOGS})",
    )

    p_status = sub.add_parser("status", help="summarize one catalog")
    _add_catalog_flag(p_status)

    p_list = sub.add_parser("list", help="list receipts in a catalog")
    _add_catalog_flag(p_list)
    p_list.add_argument("-q", "--query", default=None, help="filter by path/symbol/sha substring")
    p_list.add_argument("-n", "--limit", type=int, default=None, help="max rows")

    p_find = sub.add_parser("find", help="search symbols in a catalog index")
    _add_catalog_flag(p_find)
    p_find.add_argument("query")

    p_show = sub.add_parser("show", help="show one receipt by rel path, basename, or sha")
    _add_catalog_flag(p_show)
    p_show.add_argument("key", help="rel path, file name, or sha256 (prefix ok)")

    p_plan = sub.add_parser(
        "plan",
        help="select units + close local deps (no compile) — foresight before restack",
    )
    _add_catalog_flag(p_plan)
    p_plan.add_argument(
        "seeds",
        nargs="+",
        help="rel path, basename, sha, or class name seeds",
    )

    p_stack = sub.add_parser(
        "stack",
        help="selective restack: plan → compile → produce → direct check",
    )
    _add_catalog_flag(p_stack)
    p_stack.add_argument("seeds", nargs="+", help="seed units to include")
    p_stack.add_argument("--name", required=True, help="batch/package name")
    p_stack.add_argument("-o", "--out", required=True, help="output project directory")
    p_stack.add_argument("--work", default=None, help="keep staging dir (default: temp)")
    p_stack.add_argument(
        "--no-check",
        action="store_true",
        help="skip director check after produce",
    )
    p_stack.add_argument(
        "--force",
        action="store_true",
        help="stack even when plan has missing/ambiguous local deps",
    )

    p_dash = sub.add_parser("dashboard", help="local shelf UI (browse / plan / stack)")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8787)
    p_dash.add_argument(
        "--root",
        default=None,
        help=f"catalogs root (default: {DEFAULT_CATALOGS})",
    )
    _add_catalog_flag(p_dash)
    p_dash.add_argument(
        "--no-open",
        action="store_true",
        help="do not open a browser",
    )

    # Thin delegates so one binary covers the pipeline too.
    p_collect = sub.add_parser("collect", help="delegate to collect")
    p_collect.add_argument("args", nargs=argparse.REMAINDER)

    p_compile = sub.add_parser("compile", help="delegate to compile")
    p_compile.add_argument("args", nargs=argparse.REMAINDER)

    p_produce = sub.add_parser("produce", help="delegate to produce")
    p_produce.add_argument("args", nargs=argparse.REMAINDER)

    p_direct = sub.add_parser("direct", help="delegate to direct")
    p_direct.add_argument("args", nargs=argparse.REMAINDER)

    p_pipe = sub.add_parser("pipeline", help="delegate to pipeline")
    p_pipe.add_argument("args", nargs=argparse.REMAINDER)

    args = p.parse_args(argv)

    try:
        if args.cmd == "catalogs":
            root = Path(args.root).expanduser() if args.root else DEFAULT_CATALOGS
            rows = list_catalogs(root)
            _print({"root": str(root.expanduser().resolve()), "catalogs": rows})
            return 0 if rows else 1

        if args.cmd == "status":
            catalog = default_catalog(args.catalog)
            _print(catalog_summary(catalog))
            return 0

        if args.cmd == "list":
            catalog = default_catalog(args.catalog)
            rows = list_receipts(catalog, query=args.query, limit=args.limit)
            _print({"catalog": str(catalog), "count": len(rows), "receipts": rows})
            return 0 if rows else 1

        if args.cmd == "find":
            catalog = default_catalog(args.catalog)
            hits = search_symbols(catalog, args.query)
            _print({"catalog": str(catalog), "query": args.query, "hits": hits})
            return 0 if hits else 1

        if args.cmd == "show":
            catalog = default_catalog(args.catalog)
            _print(show_receipt(catalog, args.key))
            return 0

        if args.cmd == "plan":
            catalog = default_catalog(args.catalog)
            result = stack_plan(catalog, args.seeds)
            _print(result)
            if result["missing_local"] or result["ambiguous_local"]:
                return 2
            return 0 if result["count"] else 1

        if args.cmd == "stack":
            catalog = default_catalog(args.catalog)
            result = stack_build(
                catalog,
                args.seeds,
                name=args.name,
                out=Path(args.out),
                work=Path(args.work) if args.work else None,
                check=not args.no_check,
                force=args.force,
            )
            _print(result)
            roster = result.get("roster") or {}
            if result.get("compile_errors"):
                return 2
            if roster and not roster.get("local_graph_ok"):
                return 2
            if roster and not roster.get("ready"):
                return 3
            return 0

        if args.cmd == "dashboard":
            from receipt_cli.dashboard import serve

            catalog = Path(args.catalog).expanduser() if args.catalog else None
            root = Path(args.root).expanduser() if args.root else None
            return serve(
                host=args.host,
                port=args.port,
                catalogs_root=root,
                catalog=catalog,
                open_browser=not args.no_open,
            )

        if args.cmd == "collect":
            from collector.cli import main as collect_main

            return collect_main(_remainder(args.args))

        if args.cmd == "compile":
            from compiler.cli import main as compile_main

            return compile_main(_remainder(args.args))

        if args.cmd == "produce":
            from producer.cli import main as produce_main

            return produce_main(_remainder(args.args))

        if args.cmd == "direct":
            from director.cli import main as direct_main

            return direct_main(_remainder(args.args))

        if args.cmd == "pipeline":
            from pipeline.cli import main as pipeline_main

            return pipeline_main(_remainder(args.args))

    except (ShelfError, StackError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 1


def _remainder(args: list[str]) -> list[str]:
    # argparse.REMAINDER may keep a leading '--'
    if args[:1] == ["--"]:
        return args[1:]
    return list(args)
