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
        description="collect → compile → produce; optional explicit director check",
        epilog=(
            "Build-only exit codes: 0 built, 1 input/build error. With --check: "
            "2 local graph broken, 3 imports failing (not ready)."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("tree", help="local tree or GitHub spec")
    b.add_argument("--name", required=True)
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--work", default=None, help="staging dir (default: temp)")
    b.add_argument("--ref", default=None, help="GitHub ref (branch, tag, or SHA)")
    b.add_argument(
        "--check",
        action="store_true",
        help="explicitly import produced modules through Director after build",
    )
    args = p.parse_args(argv)
    if args.cmd != "build":
        return 1
    try:
        if args.work:
            work = Path(args.work)
            result = build(
                args.tree,
                args.name,
                Path(args.out),
                work,
                ref=args.ref,
                check=args.check,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="pipeline-") as tmp:
                result = build(
                    args.tree,
                    args.name,
                    Path(args.out),
                    Path(tmp),
                    ref=args.ref,
                    check=args.check,
                )
    except (CollectError, GitHubError, ProduceError, ReceiptIOError, SystemExit) as exc:
        msg = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, str) else str(exc)
        if msg:
            print(msg, file=sys.stderr)
        return 1

    roster = result.get("roster")
    summary = {
        "project": result["project"],
        "package": result.get("package"),
        "units": result["units"],
        "compile_errors": len(result.get("compile_errors") or []),
        "execution": result["execution"],
        "ready": roster.get("ready") if roster else None,
        "ok": len(roster.get("ok") or []) if roster else None,
        "import_error": len(roster.get("import_error") or []) if roster else None,
    }
    print(json.dumps(summary, indent=2))

    if result.get("compile_errors"):
        return 1
    if roster is None:
        return 0
    if not roster["local_graph_ok"]:
        return 2
    if not roster["ready"]:
        return 3
    return 0
