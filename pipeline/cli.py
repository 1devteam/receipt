from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from collector.collect import CollectError
from collector.github import GitHubError
from common.io import ReceiptIOError
from pipeline.build import build
from producer.produce import ProduceError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="pipeline",
        description="collect → compile → produce → direct check",
        epilog=(
            "Exit codes: 0 ready, 1 input/build error, 2 local graph broken, "
            "3 imports failing (not ready)."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("tree", help="local tree or GitHub spec")
    b.add_argument("--name", required=True)
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--work", default=None, help="staging dir (default: temp)")
    b.add_argument("--ref", default=None, help="GitHub ref (branch, tag, or SHA)")
    args = p.parse_args(argv)
    if args.cmd != "build":
        return 1
    try:
        if args.work:
            work = Path(args.work)
            roster = build(args.tree, args.name, Path(args.out), work, ref=args.ref)
        else:
            with tempfile.TemporaryDirectory(prefix="pipeline-") as tmp:
                roster = build(args.tree, args.name, Path(args.out), Path(tmp), ref=args.ref)
    except (CollectError, GitHubError, ProduceError, ReceiptIOError, SystemExit) as exc:
        msg = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, str) else str(exc)
        if msg:
            print(msg, file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "project": roster["project"],
                "units": roster["units"],
                "ok": len(roster["ok"]),
                "import_error": len(roster["import_error"]),
                "ready": roster["ready"],
            },
            indent=2,
        )
    )
    if not roster["local_graph_ok"]:
        return 2
    if not roster["ready"]:
        return 3
    return 0
