from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.io import ReceiptIOError
from compiler.compile import compile_receipts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="compile",
        description="Compile receipts into owned modules",
        epilog="Exit codes: 0 all units compiled, 1 input/usage, 2 partial (some errors).",
    )
    p.add_argument("receipts", help="receipts.json or catalog receipts.json")
    p.add_argument("--name", required=True, help="batch name (becomes i_<name>)")
    p.add_argument("-o", "--out", required=True, help="staging directory")
    args = p.parse_args(argv)
    try:
        meta = compile_receipts(Path(args.receipts), args.name, Path(args.out))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        raise
    except ReceiptIOError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "compile": str(Path(args.out).resolve()),
                "package": meta["package"],
                "units": len(meta["units"]),
                "errors": len(meta["errors"]),
                "warnings": len(meta.get("warnings") or []),
            },
            indent=2,
        )
    )
    if not meta["units"]:
        return 1
    if meta["errors"]:
        return 2
    return 0
