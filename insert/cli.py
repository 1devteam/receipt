from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    print(
        "insert is legacy; Receipt CLI is `receipt`",
        file=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        prog="insert",
        description="Insert house. Loads owned units. Compile with insertc.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ls", help="list housed batches")

    p_show = sub.add_parser("show", help="show one unit")
    p_show.add_argument("insert_id")

    p_call = sub.add_parser("call", help="call a housed unit")
    p_call.add_argument("insert_id")
    p_call.add_argument("target", help="Class.method or function")
    p_call.add_argument("args", nargs="*")

    args = parser.parse_args(argv)

    from insert.host import call, exports, list_manifests, load_unit

    if args.cmd == "ls":
        rows = []
        for m in list_manifests():
            rows.append(
                {
                    "name": m["name"],
                    "package": m["package"],
                    "units": len(m.get("units", [])),
                    "skipped": len(m.get("skipped", [])),
                }
            )
        print(json.dumps(rows, indent=2))
        return 0

    if args.cmd == "show":
        mod = load_unit(args.insert_id)
        print(
            json.dumps(
                {
                    "id": getattr(mod, "INSERT_ID", args.insert_id),
                    "owner": getattr(mod, "INSERT_OWNER", None),
                    "origin": getattr(mod, "INSERT_ORIGIN", None),
                    "exports": exports(args.insert_id),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "call":
        print(call(args.insert_id, args.target, args.args))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
