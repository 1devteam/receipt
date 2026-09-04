from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from producer.produce import ProduceError, produce


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="produce",
        description="Write a project folder from compile staging",
        epilog="Exit codes: 0 ok, 1 invalid staging/input.",
    )
    p.add_argument("compile_dir", help="compile staging directory")
    p.add_argument("-o", "--out", required=True, help="project directory")
    args = p.parse_args(argv)
    try:
        meta = produce(Path(args.compile_dir), Path(args.out))
    except ProduceError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "project": meta["project"],
                "package": meta["package"],
                "units": len(meta["units"]),
            },
            indent=2,
        )
    )
    return 0
