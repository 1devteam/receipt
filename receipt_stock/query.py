from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from common.io import read_json, write_json
from receipt_graft.evidence import canonical_fingerprint

STOCK_UNITS_SCHEMA = "receipt.stock.units.v1"


class StockQueryError(ValueError):
    """Invalid or missing Receipt stock query data."""


def _portable_identity(identity: dict[str, Any]) -> dict[str, Any]:
    """Retain stable source identity while excluding machine-local origin data."""
    keys = ("schema", "kind", "repository", "commit", "path", "source_sha256")
    return {key: identity.get(key) for key in keys if key in identity}


def _symbol_names(rec: dict[str, Any]) -> list[str]:
    contracts = rec.get("contracts") if isinstance(rec.get("contracts"), dict) else {}
    names: set[str] = set()
    for item in contracts.get("classes") or rec.get("classes") or []:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
        if isinstance(item, dict):
            for method in item.get("methods") or []:
                if isinstance(method, dict) and method.get("name"):
                    names.add(str(method["name"]))
    for item in contracts.get("functions") or rec.get("functions") or []:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return sorted(names)


def _effect_kinds(rec: dict[str, Any]) -> list[str]:
    topology = rec.get("topology") if isinstance(rec.get("topology"), dict) else {}
    found: set[str] = set()
    for effect in topology.get("effects") or []:
        if isinstance(effect, dict):
            kind = effect.get("kind") or effect.get("effect")
            if kind:
                found.add(str(kind))
        elif effect:
            found.add(str(effect))
    return sorted(found)


def build_unit_index(stock_root: Path | str, source_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build a portable, cross-catalog unit index over admitted Receipt stock."""
    root = Path(stock_root).expanduser().resolve()
    units: list[dict[str, Any]] = []

    for source in source_rows:
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        catalog = root / "catalogs" / source_id
        receipts_path = catalog / "receipts.json"
        if not receipts_path.is_file():
            raise StockQueryError(f"missing stock catalog receipts: {receipts_path}")
        payload = read_json(receipts_path)
        for rec in payload.get("files") or []:
            if not isinstance(rec, dict):
                continue
            stock = rec.get("stock") if isinstance(rec.get("stock"), dict) else {}
            admission = stock.get("admission") if isinstance(stock.get("admission"), dict) else {}
            identity = rec.get("source_identity") if isinstance(rec.get("source_identity"), dict) else {}
            deps = rec.get("dependencies") if isinstance(rec.get("dependencies"), dict) else {}
            tags = sorted({str(tag) for tag in admission.get("capability_tags") or [] if tag})
            rel = str(rec.get("rel") or "")
            sha = str(rec.get("source_sha256") or rec.get("sha256") or "")
            if not rel or not sha:
                continue
            units.append(
                {
                    "id": f"{source_id}:{sha}",
                    "source_id": source_id,
                    "repository": stock.get("repository") or source.get("repository"),
                    "commit": stock.get("commit") or source.get("commit"),
                    "subpath": stock.get("subpath") or source.get("subpath"),
                    "mount": stock.get("mount") or source.get("mount"),
                    "license": stock.get("license") or source.get("license"),
                    "rel": rel,
                    "original_rel": rec.get("stock_original_rel"),
                    "source_sha256": sha,
                    "normalized_sha256": rec.get("normalized_sha256"),
                    "source_identity": _portable_identity(identity),
                    "decision": admission.get("decision"),
                    "score": admission.get("score"),
                    "capability_tags": tags,
                    "symbols": _symbol_names(rec),
                    "external_dependencies": sorted(str(dep) for dep in deps.get("external") or []),
                    "effects": _effect_kinds(rec),
                    "has_main": bool(rec.get("has_main")),
                    "syntax_ok": bool(rec.get("syntax_ok")),
                    "catalog_rel": f"catalogs/{source_id}",
                    "grants_execution_authority": False,
                }
            )

    units.sort(key=lambda row: (str(row.get("source_id") or ""), str(row.get("rel") or "")))
    tag_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for unit in units:
        decision = str(unit.get("decision") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        for tag in unit.get("capability_tags") or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    index: dict[str, Any] = {
        "schema": STOCK_UNITS_SCHEMA,
        "purpose": (
            "Portable cross-catalog index for discovering Receipt stock units by proven "
            "capability, contract symbol, dependency and source identity."
        ),
        "units": units,
        "counts": {
            "units": len(units),
            "decisions": dict(sorted(decision_counts.items())),
            "capability_tags": dict(sorted(tag_counts.items())),
        },
        "security": {
            "contains_machine_local_origin": False,
            "contains_raw_source": False,
            "contains_normalized_source": False,
        },
        "grants_execution_authority": False,
    }
    index["fingerprint"] = canonical_fingerprint(index)
    return index


def write_unit_index(stock_root: Path | str, source_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    root = Path(stock_root).expanduser().resolve()
    index = build_unit_index(root, source_rows)
    write_json(root / "stock-units.v1.json", index)
    return index


def load_unit_index(stock_root: Path | str) -> dict[str, Any]:
    root = Path(stock_root).expanduser().resolve()
    path = root / "stock-units.v1.json"
    if not path.is_file():
        raise StockQueryError(f"missing stock unit index: {path}")
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema") != STOCK_UNITS_SCHEMA:
        raise StockQueryError(f"invalid stock unit index: {path}")
    return data


def find_units(
    stock_root: Path | str,
    *,
    query: str | None = None,
    capabilities: Iterable[str] | None = None,
    require_all_capabilities: bool = True,
    source_id: str | None = None,
    decision: str | None = None,
    external: str | None = None,
    limit: int | None = 50,
) -> list[dict[str, Any]]:
    """Search all materialized stock catalogs without flattening provenance."""
    data = load_unit_index(stock_root)
    wanted_tags = {str(tag).strip().lower() for tag in (capabilities or []) if str(tag).strip()}
    q = (query or "").strip().lower()
    source_filter = (source_id or "").strip()
    decision_filter = (decision or "").strip().lower()
    external_filter = (external or "").strip().lower()
    hits: list[dict[str, Any]] = []

    for unit in data.get("units") or []:
        if not isinstance(unit, dict):
            continue
        if source_filter and unit.get("source_id") != source_filter:
            continue
        if decision_filter and str(unit.get("decision") or "").lower() != decision_filter:
            continue
        tags = {str(tag).lower() for tag in unit.get("capability_tags") or []}
        if wanted_tags:
            if require_all_capabilities and not wanted_tags <= tags:
                continue
            if not require_all_capabilities and not (wanted_tags & tags):
                continue
        if external_filter:
            externals = {str(dep).lower() for dep in unit.get("external_dependencies") or []}
            if not any(external_filter == dep or external_filter in dep for dep in externals):
                continue
        if q:
            searchable = " ".join(
                [
                    str(unit.get("source_id") or ""),
                    str(unit.get("repository") or ""),
                    str(unit.get("rel") or ""),
                    str(unit.get("mount") or ""),
                    " ".join(str(name) for name in unit.get("symbols") or []),
                    " ".join(str(tag) for tag in unit.get("capability_tags") or []),
                    " ".join(str(dep) for dep in unit.get("external_dependencies") or []),
                    " ".join(str(effect) for effect in unit.get("effects") or []),
                ]
            ).lower()
            if q not in searchable:
                continue
        hits.append(unit)
        if limit is not None and limit >= 0 and len(hits) >= limit:
            break
    return hits
