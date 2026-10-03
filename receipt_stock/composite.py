from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable

from collector.onboard import modules_from_rels, onboard_source, tops_from_rels
from common.io import read_json, write_json
from receipt_graft.evidence import canonical_fingerprint

STOCK_COMPOSITE_SCHEMA = "receipt.stock.composite.v1"


class StockCompositeError(ValueError):
    """Invalid or conflicting multi-source stock composition."""


def _source_fingerprints(root: Path, source_ids: list[str]) -> dict[str, str]:
    index_path = root / "stock-index.v1.json"
    if not index_path.is_file():
        raise StockCompositeError(f"missing stock index: {index_path}")
    index = read_json(index_path)
    rows = {
        str(row.get("id") or ""): str(row.get("stock_graph_fingerprint") or "")
        for row in index.get("sources") or []
        if isinstance(row, dict)
    }
    result: dict[str, str] = {}
    for source_id in source_ids:
        fingerprint = rows.get(source_id)
        if not fingerprint:
            raise StockCompositeError(f"stock source lacks graph fingerprint: {source_id}")
        result[source_id] = fingerprint
    return result


def _copy_if_present(source: Path, dest: Path) -> None:
    if not source.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(source, dest)


def _symbol_index(files: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    symbols: dict[str, list[dict[str, Any]]] = {}
    for rec in files:
        contracts = rec.get("contracts") if isinstance(rec.get("contracts"), dict) else {}
        names: set[str] = set()
        for cls in contracts.get("classes") or []:
            if isinstance(cls, dict) and cls.get("name"):
                names.add(str(cls["name"]))
            if isinstance(cls, dict):
                for method in cls.get("methods") or []:
                    if isinstance(method, dict) and method.get("name") and method.get("name") != "__init__":
                        names.add(str(method["name"]))
        for fn in contracts.get("functions") or []:
            if isinstance(fn, dict) and fn.get("name"):
                names.add(str(fn["name"]))
        for name in names:
            symbols.setdefault(name, []).append(
                {
                    "rel": rec.get("rel"),
                    "sha256": rec.get("sha256"),
                    "source_id": (rec.get("stock") or {}).get("bootstrap_source_id"),
                }
            )
    return symbols


def materialize_composite(
    stock_root: Path | str,
    source_ids: Iterable[str],
    *,
    stock_index_fingerprint: str,
) -> tuple[Path, dict[str, Any]]:
    """Materialize a deterministic union catalog and recompute cross-source dependencies."""
    root = Path(stock_root).expanduser().resolve()
    selected_sources = sorted({str(value).strip() for value in source_ids if str(value).strip()})
    if len(selected_sources) < 2:
        raise StockCompositeError("composite requires at least two source catalogs")

    source_fingerprints = _source_fingerprints(root, selected_sources)
    identity = {
        "schema": STOCK_COMPOSITE_SCHEMA,
        "stock_index_fingerprint": stock_index_fingerprint,
        "source_ids": selected_sources,
        "source_catalog_fingerprints": source_fingerprints,
    }
    composite_id = canonical_fingerprint(identity)
    catalog = root / "composites" / composite_id
    receipts_path = catalog / "receipts.json"
    artifact_path = catalog / "composite.v1.json"

    if receipts_path.is_file() and artifact_path.is_file():
        artifact = read_json(artifact_path)
        if artifact.get("fingerprint") == composite_id:
            return catalog, artifact

    if catalog.exists():
        shutil.rmtree(catalog)
    for folder in ("raw", "normalized", "contracts", "dependencies", "topology"):
        (catalog / folder).mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    by_rel: dict[str, dict[str, Any]] = {}
    collisions: list[dict[str, Any]] = []
    licenses: dict[str, str] = {}
    mounts: dict[str, str] = {}

    for source_id in selected_sources:
        source_catalog = root / "catalogs" / source_id
        payload = read_json(source_catalog / "receipts.json")
        for rec in payload.get("files") or []:
            if not isinstance(rec, dict):
                continue
            rel = str(rec.get("rel") or "")
            sha = str(rec.get("source_sha256") or rec.get("sha256") or "")
            if not rel or not sha:
                raise StockCompositeError(f"invalid source receipt in {source_id}: rel/hash missing")
            previous = by_rel.get(rel)
            if previous is not None:
                previous_sha = str(previous.get("source_sha256") or previous.get("sha256") or "")
                if previous_sha != sha:
                    collisions.append(
                        {
                            "rel": rel,
                            "left_source": (previous.get("stock") or {}).get("bootstrap_source_id"),
                            "left_sha256": previous_sha,
                            "right_source": source_id,
                            "right_sha256": sha,
                        }
                    )
                    continue
                continue

            item = dict(rec)
            by_rel[rel] = item
            rows.append(item)
            stock = item.get("stock") if isinstance(item.get("stock"), dict) else {}
            licenses[source_id] = str(stock.get("license") or "")
            mounts[source_id] = str(stock.get("mount") or "")
            raw = item.get("raw")
            normalized = item.get("copy") or item.get("normalized")
            if raw:
                _copy_if_present(source_catalog / str(raw), catalog / str(raw))
            if normalized:
                _copy_if_present(source_catalog / str(normalized), catalog / str(normalized))

    if collisions:
        raise StockCompositeError(
            "logical path collisions across stock sources: "
            + "; ".join(
                f"{row['rel']} ({row['left_source']} != {row['right_source']})"
                for row in collisions[:10]
            )
        )

    rels = [str(rec["rel"]) for rec in rows]
    tops = tops_from_rels(rels)
    modules = modules_from_rels(rels)
    module_source: dict[str, str] = {}
    for rec in rows:
        source_id = str((rec.get("stock") or {}).get("bootstrap_source_id") or "")
        rel = str(rec.get("rel") or "")
        if rel.endswith("/__init__.py"):
            module = rel[: -len("/__init__.py")].replace("/", ".")
        elif rel.endswith(".py"):
            module = rel[:-3].replace("/", ".")
        else:
            continue
        module_source[module] = source_id

    recomputed: list[dict[str, Any]] = []
    cross_source_edges: list[dict[str, Any]] = []
    for rec in rows:
        item = dict(rec)
        normalized = item.get("copy") or item.get("normalized")
        if not normalized:
            raise StockCompositeError(f"composite unit lacks normalized source: {item.get('rel')}")
        source_path = catalog / str(normalized)
        if not source_path.is_file():
            raise StockCompositeError(f"missing composite normalized source: {source_path}")
        info = onboard_source(
            source_path.read_text(encoding="utf-8", errors="replace"),
            tops=tops,
            local_modules=modules,
        )
        item["imports"] = info.get("imports") or []
        item["dependencies"] = info.get("dependencies") or {}
        item["topology"] = info.get("topology") or {}
        item["contracts"] = info.get("contracts") or item.get("contracts") or {}
        item["classes"] = info.get("classes") or item.get("classes") or []
        item["functions"] = info.get("functions") or item.get("functions") or []
        sha = str(item.get("source_sha256") or item.get("sha256") or "")
        write_json(catalog / "contracts" / f"{sha}.json", item["contracts"])
        write_json(catalog / "dependencies" / f"{sha}.json", item["dependencies"])
        write_json(catalog / "topology" / f"{sha}.json", item["topology"])

        from_source = str((item.get("stock") or {}).get("bootstrap_source_id") or "")
        for module in item["dependencies"].get("local") or []:
            to_source = module_source.get(str(module))
            if to_source and to_source != from_source:
                cross_source_edges.append(
                    {
                        "from_rel": item.get("rel"),
                        "from_source": from_source,
                        "module": module,
                        "to_source": to_source,
                    }
                )
        recomputed.append(item)

    payload: dict[str, Any] = {
        "root": f"receipt-stock://composite/{composite_id}",
        "catalog": str(catalog),
        "source": {
            "kind": "receipt-stock-composite",
            "id": composite_id,
            "source_ids": selected_sources,
        },
        "onboard": {
            "preserve": ["raw_source", "source_identity", "stock_provenance"],
            "normalize": ["existing_normalized_stock"],
            "extract": ["contracts", "dependencies", "topology"],
            "dependency_scope": "selected-source-union",
        },
        "files": recomputed,
        "skipped": [],
    }
    write_json(receipts_path, payload)
    write_json(catalog / "index.json", _symbol_index(recomputed))

    artifact: dict[str, Any] = {
        **identity,
        "fingerprint": composite_id,
        "catalog_rel": f"composites/{composite_id}",
        "mounts": mounts,
        "licenses": licenses,
        "license_compatibility_not_determined": True,
        "units": len(recomputed),
        "collisions": collisions,
        "cross_source_local_edges": sorted(
            cross_source_edges,
            key=lambda row: (
                str(row.get("from_source") or ""),
                str(row.get("from_rel") or ""),
                str(row.get("module") or ""),
                str(row.get("to_source") or ""),
            ),
        ),
        "cross_source_local_edge_count": len(cross_source_edges),
        "security": {
            "contains_machine_local_origin": False,
            "contains_raw_source": False,
            "contains_normalized_source": False,
        },
        "grants_execution_authority": False,
        "implements_plan": False,
        "change_authority": "not-determined",
    }
    write_json(artifact_path, artifact)
    return catalog, artifact
