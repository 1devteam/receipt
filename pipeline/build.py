from __future__ import annotations

from pathlib import Path

from collector.collect import CollectError, collect_to
from compiler.compile import compile_receipts
from director.check import check_project
from producer.produce import produce
from receipt_graft.integration import persist_collection_graph


def build(
    tree: Path | str,
    name: str,
    out: Path,
    work: Path,
    *,
    ref: str | None = None,
    check: bool = False,
) -> dict:
    """Collect, graph, compile, and produce. Runtime imports occur only when ``check=True``."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    receipts = work / "receipts.json"
    compile_dir = work / "compile"
    data = collect_to(tree, receipts, ref=ref)
    if not data["files"]:
        raise CollectError(f"no .py files collected from {tree}")
    graft = persist_collection_graph(data, receipts)
    meta = compile_receipts(receipts, name, compile_dir)
    if not meta["units"]:
        raise SystemExit("compile produced no units")
    project = produce(compile_dir, out)
    roster = check_project(out) if check else None
    return {
        "project": project.get("project") if isinstance(project, dict) else str(Path(out).resolve()),
        "package": meta.get("package"),
        "units": len(meta.get("units") or []),
        "compile_errors": meta.get("errors") or [],
        "internal_graft": graft,
        "execution": {
            "requested": bool(check),
            "performed": roster is not None,
            "boundary": "explicit",
        },
        "roster": roster,
    }
