from __future__ import annotations

from pathlib import Path

from common.io import read_json


def find_symbol(catalog: Path, query: str) -> list[dict]:
    catalog = catalog.resolve()
    index = read_json(catalog / "index.json")
    q = query.strip()
    hits = []
    for name, rows in index.items():
        if q.lower() not in name.lower():
            continue
        for row in rows:
            hits.append({"symbol": name, **row})
    hits.sort(key=lambda r: (r["symbol"] != q, r["symbol"], r["rel"]))
    return hits
