from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from insertc.compile import compile_tree, default_out


def main(argv: list[str] | None = None) -> int:
    print(
        "insertc is legacy; Receipt CLI is `receipt`",
        file=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        prog="insertc",
        description="Companion compiler. Emits a project folder with contracts, deps, structure.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("compile", help="compile .py tree into its own project folder")
    p.add_argument("path")
    p.add_argument("--name", required=True)
    p.add_argument(
        "--out",
        default=None,
        help="project folder (default: ../compiled/<name> next to insert, not inside insertc)",
    )
    args = parser.parse_args(argv)

    if args.cmd == "compile":
        out = Path(args.out) if args.out else default_out(args.name)
        manifest = compile_tree(Path(args.path), args.name, out=out)
        print(
            json.dumps(
                {
                    "compiler": "insertc",
                    "project": manifest["project"],
                    "package": manifest["package"],
                    "units": len(manifest["units"]),
                    "skipped": len(manifest["skipped"]),
                    "wrote": [
                        "manifest.json",
                        "contracts.json",
                        "dependencies.json",
                        "structure.json",
                        "src/",
                    ],
                },
                indent=2,
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
