from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from common.io import read_json
from receipt_graft.graph import STOCK_GRAPH_SCHEMA, write_stock_graph


def graph_path_for_output(out: Path) -> Path:
    out = Path(out).expanduser().resolve()
    if out.suffix == ".json":
        return out.with_name(f"{out.stem}.graft.json")
    return out / "graft" / "stock-graph.v1.json"


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


def reconstruct_catalog(catalog: Path) -> dict[str, Any]:
    catalog = Path(catalog).expanduser().resolve()
    receipts_path = catalog if catalog.suffix == ".json" else catalog / "receipts.json"
    data = read_json(receipts_path)
    if not isinstance(data, dict):
        raise ValueError(f"invalid receipts payload: {receipts_path}")
    return persist_collection_graph(data, catalog)
