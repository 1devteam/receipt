from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from common.io import write_json
from receipt_cli.stack import plan as stack_plan
from receipt_cli.stack import stack as stack_build
from receipt_graft.evidence import canonical_fingerprint
from receipt_stock.composite import materialize_composite
from receipt_stock.query import load_unit_index

STOCK_SELECTION_SCHEMA = "receipt.stock.selection.v1"


class StockBuildError(ValueError):
    """Invalid or unsafe request to build from federated Receipt stock."""


def _resolve_units(stock_root: Path | str, unit_ids: Iterable[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = Path(stock_root).expanduser().resolve()
    index = load_unit_index(root)
    units = [unit for unit in index.get("units") or [] if isinstance(unit, dict)]
    wanted = [str(value).strip() for value in unit_ids if str(value).strip()]
    if not wanted:
        raise StockBuildError("at least one stock unit id is required")

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in wanted:
        exact = [unit for unit in units if unit.get("id") == key]
        matches = exact or [unit for unit in units if str(unit.get("id") or "").startswith(key)]
        if not matches:
            raise StockBuildError(f"no stock unit matching {key!r}")
        if len(matches) != 1:
            raise StockBuildError(
                f"ambiguous stock unit {key!r}; matches: {[unit.get('id') for unit in matches[:10]]}"
            )
        unit = matches[0]
        unit_id = str(unit.get("id") or "")
        if unit_id not in seen:
            seen.add(unit_id)
            selected.append(unit)
    return index, selected


def _selection(
    index: dict[str, Any],
    selected: list[dict[str, Any]],
    plan_data: dict[str, Any],
    *,
    composite: dict[str, Any] | None,
) -> dict[str, Any]:
    source_ids = sorted({str(unit.get("source_id") or "") for unit in selected})
    units = [
        {
            "id": unit.get("id"),
            "source_id": unit.get("source_id"),
            "repository": unit.get("repository"),
            "commit": unit.get("commit"),
            "subpath": unit.get("subpath"),
            "mount": unit.get("mount"),
            "license": unit.get("license"),
            "rel": unit.get("rel"),
            "original_rel": unit.get("original_rel"),
            "source_sha256": unit.get("source_sha256"),
            "normalized_sha256": unit.get("normalized_sha256"),
            "source_identity": unit.get("source_identity"),
            "decision": unit.get("decision"),
            "score": unit.get("score"),
            "capability_tags": list(unit.get("capability_tags") or []),
            "grants_execution_authority": False,
        }
        for unit in selected
    ]
    artifact: dict[str, Any] = {
        "schema": STOCK_SELECTION_SCHEMA,
        "purpose": (
            "Bind explicit federated-stock selections to the exact source or composite "
            "catalog and existing Receipt stack plan that will compile them."
        ),
        "stock_index_fingerprint": index.get("fingerprint"),
        "source_ids": source_ids,
        "repositories": sorted({str(unit.get("repository") or "") for unit in selected}),
        "commits": sorted({str(unit.get("commit") or "") for unit in selected}),
        "mounts": sorted({str(unit.get("mount") or "") for unit in selected}),
        "licenses": sorted({str(unit.get("license") or "") for unit in selected}),
        "license_compatibility_not_determined": len(source_ids) > 1,
        "selected_units": units,
        "requested_rels": sorted(str(unit.get("rel") or "") for unit in selected),
        "resolved_plan": {
            "seeds": list(plan_data.get("seeds") or []),
            "count": plan_data.get("count"),
            "units": list(plan_data.get("units") or []),
            "missing_local": list(plan_data.get("missing_local") or []),
            "ambiguous_local": list(plan_data.get("ambiguous_local") or []),
            "external": list(plan_data.get("external") or []),
        },
        "composite": (
            {
                "schema": composite.get("schema"),
                "fingerprint": composite.get("fingerprint"),
                "source_ids": composite.get("source_ids"),
                "units": composite.get("units"),
                "cross_source_local_edge_count": composite.get("cross_source_local_edge_count"),
            }
            if composite
            else None
        ),
        "compiler": "receipt_cli.stack",
        "cross_source_compilation": bool(composite),
        "grants_execution_authority": False,
        "implements_plan": False,
        "change_authority": "not-determined",
    }
    artifact["fingerprint"] = canonical_fingerprint(artifact)
    return artifact


def plan_stock(stock_root: Path | str, unit_ids: Iterable[str]) -> dict[str, Any]:
    root = Path(stock_root).expanduser().resolve()
    index, selected = _resolve_units(root, unit_ids)
    source_ids = sorted({str(unit.get("source_id") or "") for unit in selected})
    if "" in source_ids:
        raise StockBuildError("selected stock unit is missing source_id")

    composite: dict[str, Any] | None = None
    if len(source_ids) == 1:
        catalog = root / "catalogs" / source_ids[0]
        if not (catalog / "receipts.json").is_file():
            raise StockBuildError(f"missing source catalog: {catalog}")
    else:
        catalog, composite = materialize_composite(
            root,
            source_ids,
            stock_index_fingerprint=str(index.get("fingerprint") or ""),
        )

    rels = [str(unit.get("rel") or "") for unit in selected]
    plan_data = stack_plan(catalog, rels)
    selection = _selection(index, selected, plan_data, composite=composite)
    return {
        "stock_root": str(root),
        "catalog": str(catalog),
        "selection": selection,
        "composite": composite,
        "plan": plan_data,
        "grants_execution_authority": False,
    }


def stack_stock(
    stock_root: Path | str,
    unit_ids: Iterable[str],
    *,
    name: str,
    out: Path | str,
    work: Path | str | None = None,
    check: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    planned = plan_stock(stock_root, unit_ids)
    selection = planned["selection"]
    composite = planned.get("composite")
    plan_data = planned["plan"]
    catalog = Path(planned["catalog"])
    out_path = Path(out).expanduser().resolve()

    result = stack_build(
        catalog,
        list(plan_data.get("seeds") or []),
        name=name,
        out=out_path,
        work=Path(work).expanduser().resolve() if work is not None else None,
        check=check,
        force=force,
    )

    stock_dir = out_path / ".receipt" / "stock"
    stock_dir.mkdir(parents=True, exist_ok=True)
    artifact = stock_dir / "selection.v1.json"
    write_json(artifact, selection)
    composite_path: Path | None = None
    if isinstance(composite, dict):
        composite_path = stock_dir / "composite.v1.json"
        write_json(composite_path, composite)

    return {
        **result,
        "stock_selection": {
            "schema": selection.get("schema"),
            "artifact": str(artifact),
            "fingerprint": selection.get("fingerprint"),
            "source_ids": selection.get("source_ids"),
            "cross_source_compilation": selection.get("cross_source_compilation"),
            "selected_units": len(selection.get("selected_units") or []),
            "grants_execution_authority": False,
        },
        "stock_composite": (
            {
                "schema": composite.get("schema"),
                "artifact": str(composite_path),
                "fingerprint": composite.get("fingerprint"),
                "source_ids": composite.get("source_ids"),
                "units": composite.get("units"),
                "cross_source_local_edge_count": composite.get("cross_source_local_edge_count"),
                "license_compatibility_not_determined": True,
                "grants_execution_authority": False,
            }
            if isinstance(composite, dict)
            else None
        ),
    }
