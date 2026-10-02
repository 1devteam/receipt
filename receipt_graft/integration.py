from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from common.io import read_json
from receipt_graft.graph import STOCK_GRAPH_SCHEMA, write_stock_graph
from receipt_graft.impact import IMPACT_REPORT_SCHEMA, write_impact_report


def graph_path_for_output(out: Path) -> Path:
    out = Path(out).expanduser().resolve()
    if out.suffix == ".json":
        return out.with_name(f"{out.stem}.graft.json")
    return out / "graft" / "stock-graph.v1.json"


def impact_path_for_output(out: Path) -> Path:
    out = Path(out).expanduser().resolve()
    if out.suffix == ".json":
        return out.with_name(f"{out.stem}.impact.json")
    return out / "graft" / "impact.v1.json"


def persist_collection_graph(data: dict[str, Any], out: Path) -> dict[str, Any]:
    path = graph_path_for_output(out)
    graph = write_stock_graph(data, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema": STOCK_GRAPH_SCHEMA,
        "path": str(path),
        "sha256": digest,
        "inventory": graph.get("inventory") or {},
        "grants_execution_authority": False,
    }


def _receipts_for_catalog(catalog: Path) -> tuple[Path, dict[str, Any]]:
    catalog = Path(catalog).expanduser().resolve()
    receipts_path = catalog if catalog.suffix == ".json" else catalog / "receipts.json"
    data = read_json(receipts_path)
    if not isinstance(data, dict):
        raise ValueError(f"invalid receipts payload: {receipts_path}")
    return catalog, data


def reconstruct_catalog(catalog: Path) -> dict[str, Any]:
    catalog, data = _receipts_for_catalog(catalog)
    return persist_collection_graph(data, catalog)


def analyze_catalog_impact(
    catalog: Path,
    seeds: Iterable[str],
    *,
    out: Path | None = None,
) -> dict[str, Any]:
    """Rebuild current stock evidence, then derive and persist an impact/proof slice."""
    catalog, data = _receipts_for_catalog(catalog)
    graph_meta = persist_collection_graph(data, catalog)
    graph = read_json(Path(graph_meta["path"]))
    if not isinstance(graph, dict):
        raise ValueError(f"invalid graph payload: {graph_meta['path']}")

    path = Path(out).expanduser().resolve() if out else impact_path_for_output(catalog)
    report = write_impact_report(graph, seeds, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema": IMPACT_REPORT_SCHEMA,
        "path": str(path),
        "sha256": digest,
        "fingerprint": report.get("fingerprint"),
        "seeds": report.get("seeds") or [],
        "impact": report.get("impact") or {},
        "proof": {
            "candidate_tests": (report.get("proof") or {}).get("candidate_tests") or [],
            "unresolved_boundaries": len(
                (report.get("proof") or {}).get("unresolved_boundaries") or []
            ),
        },
        "grants_execution_authority": False,
    }
