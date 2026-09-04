from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.io import ReceiptIOError
from director.call import CallError, call_unit
from director.check import check_project


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="direct",
        description="First-start check and calls",
        epilog=(
            "Exit codes: 0 ready/success, 1 usage/call error, "
            "2 local graph broken, 3 imports failing (not ready)."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="account for every unit, write roster.json")
    p_check.add_argument("project")

    p_call = sub.add_parser("call", help="call a unit in a produced project")
    p_call.add_argument("project")
    p_call.add_argument("unit_id", help="unit id from manifest (e.g. i_pipe.alpha)")
    p_call.add_argument("target", help="Class.method or function name")
    p_call.add_argument("args", nargs="*")

    args = p.parse_args(argv)

    if args.cmd == "check":
        try:
            roster = check_project(Path(args.project))
        except ReceiptIOError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "project": roster["project"],
                    "units": roster["units"],
                    "ok": len(roster["ok"]),
                    "import_error": len(roster["import_error"]),
                    "missing_local": len(roster["missing_local"]),
                    "accounted": roster["accounted"],
                    "ready": roster["ready"],
                    "roster": str(Path(args.project).resolve() / "roster.json"),
                },
                indent=2,
            )
        )
        if not roster["local_graph_ok"]:
            return 2
        if not roster["ready"]:
            return 3
        return 0

    if args.cmd == "call":
        try:
            result = call_unit(Path(args.project), args.unit_id, args.target, args.args)
        except CallError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(result)
        return 0

    return 1
