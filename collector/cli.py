from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from collector.collect import CollectError, collect_to
from collector.find import find_symbol
from common.io import ReceiptIOError


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["find"]:
        p = argparse.ArgumentParser(prog="collect find")
        p.add_argument("query")
        p.add_argument("-c", "--catalog", required=True, help="catalog directory with index.json")
        args = p.parse_args(argv[1:])
        try:
            hits = find_symbol(Path(args.catalog), args.query)
        except ReceiptIOError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(hits, indent=2))
        return 0 if hits else 1

    if argv[:1] == ["scan"]:
        argv = argv[1:]

    p = argparse.ArgumentParser(
        prog="collect",
        description="Collect, strip, catalog .py files",
        epilog=(
            "Exit codes: 0 ok, 1 usage/input error, 2 empty catalog (no .py kept). "
            "-o directory writes a catalog (receipts.json + copies/ + index.json); "
            "-o file.json writes receipts only. "
            "tree may be a local path or a GitHub spec "
            "(https://github.com/owner/repo, github:owner/repo@ref, owner/repo). "
            "Private repos: GITHUB_TOKEN or GH_TOKEN."
        ),
    )
    p.add_argument(
        "tree",
        help="local .py file/tree, or GitHub URL / owner/repo[@ref][:path]",
    )
    p.add_argument(
        "-o",
        "--out",
        required=True,
        help="catalog directory, or receipts.json path",
    )
    p.add_argument(
        "--ref",
        default=None,
        help="GitHub ref (branch, tag, or SHA). overrides ref in the spec",
    )
    args = p.parse_args(argv)
    try:
        data = collect_to(args.tree, Path(args.out), ref=args.ref)
    except CollectError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ReceiptIOError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    summary = {
        "catalog": data.get("catalog") or str(Path(args.out).resolve()),
        "files": len(data["files"]),
        "skipped": len(data["skipped"]),
        "syntax_ok": sum(1 for f in data["files"] if f.get("syntax_ok")),
        "with_main_stripped": sum(1 for f in data["files"] if f.get("has_main")),
        "ownership_stripped": sum(
            1 for f in data["files"] if f.get("ownership_stripped")
        ),
        "with_contracts": sum(
            1
            for f in data["files"]
            if (f.get("contracts") or {}).get("classes")
            or (f.get("contracts") or {}).get("functions")
        ),
        "onboard": data.get("onboard"),
    }
    if data.get("source"):
        summary["source"] = data["source"]
        summary["root"] = data.get("root")
    print(json.dumps(summary, indent=2))
    return 0 if data["files"] else 2
