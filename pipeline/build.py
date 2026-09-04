from __future__ import annotations

from pathlib import Path

from collector.collect import CollectError, collect_to
from compiler.compile import compile_receipts
from director.check import check_project
from producer.produce import produce


def build(tree: Path | str, name: str, out: Path, work: Path, *, ref: str | None = None) -> dict:
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    receipts = work / "receipts.json"
    compile_dir = work / "compile"
    data = collect_to(tree, receipts, ref=ref)
    if not data["files"]:
        raise CollectError(f"no .py files collected from {tree}")
    meta = compile_receipts(receipts, name, compile_dir)
    if not meta["units"]:
        raise SystemExit("compile produced no units")
    produce(compile_dir, out)
    roster = check_project(out)
    return roster
