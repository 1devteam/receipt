from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from common.io import write_json
from receipt_stock.build import plan_stock, stack_stock
from receipt_stock.query import load_unit_index

TRIAL_SCHEMA = "receipt.validation.cross_source_stock.v1"


def _unit_by_rel(units: list[dict], source_id: str, rel: str) -> dict:
    matches = [
        unit
        for unit in units
        if unit.get("source_id") == source_id and unit.get("rel") == rel
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"expected exactly one stock unit for {source_id}:{rel}, found {len(matches)}"
        )
    return matches[0]


def run(stock_root: Path, out: Path) -> dict:
    stock_root = stock_root.expanduser().resolve()
    out = out.expanduser().resolve()
    if out.exists():
        shutil.rmtree(out)

    index = load_unit_index(stock_root)
    units = [row for row in index.get("units") or [] if isinstance(row, dict)]

    # FastAPI routing consumes Pydantic contracts in normal source. Selecting a seed
    # from each pinned pack proves that the composite can reclassify those boundaries
    # against actual permanent Receipt stock rather than a synthetic fixture only.
    fastapi = _unit_by_rel(units, "fastapi-web", "fastapi/routing.py")
    pydantic = _unit_by_rel(units, "pydantic-models", "pydantic/main.py")
    selected_ids = [fastapi["id"], pydantic["id"]]

    planned = plan_stock(stock_root, selected_ids)
    plan = planned["plan"]
    composite = planned.get("composite") or {}
    if plan.get("missing_local") or plan.get("ambiguous_local"):
        raise SystemExit(
            "cross-source plan has unresolved local dependencies: "
            f"missing={len(plan.get('missing_local') or [])} "
            f"ambiguous={len(plan.get('ambiguous_local') or [])}"
        )
    if not composite.get("cross_source_local_edge_count"):
        raise SystemExit("composite exposed no proven cross-source local edges")

    result = stack_stock(
        stock_root,
        selected_ids,
        name="fastapi_pydantic_stock",
        out=out,
        check=False,
        force=False,
    )
    violations = (result.get("compiler_contracts") or {}).get("violations") or []
    if result.get("compile_errors"):
        raise SystemExit(f"compile errors: {result['compile_errors']}")
    if violations:
        raise SystemExit(f"compiler contract violations: {violations}")
    reconciliation = result.get("graft_reconciliation") or {}
    if reconciliation.get("status") != "reconciled" or reconciliation.get("divergences"):
        raise SystemExit(f"build reconciliation failed: {reconciliation}")
    if (result.get("execution") or {}).get("performed"):
        raise SystemExit("third-party stock execution was not authorized for this trial")

    trial = {
        "schema": TRIAL_SCHEMA,
        "stock_index_fingerprint": index.get("fingerprint"),
        "selected": [
            {
                "id": unit.get("id"),
                "source_id": unit.get("source_id"),
                "repository": unit.get("repository"),
                "commit": unit.get("commit"),
                "rel": unit.get("rel"),
                "source_sha256": unit.get("source_sha256"),
            }
            for unit in (fastapi, pydantic)
        ],
        "composite": {
            "schema": composite.get("schema"),
            "fingerprint": composite.get("fingerprint"),
            "sources": composite.get("source_ids"),
            "units": composite.get("units"),
            "cross_source_local_edge_count": composite.get("cross_source_local_edge_count"),
            "license_compatibility_not_determined": composite.get(
                "license_compatibility_not_determined"
            ),
        },
        "plan": {
            "count": plan.get("count"),
            "missing_local": len(plan.get("missing_local") or []),
            "ambiguous_local": len(plan.get("ambiguous_local") or []),
            "external": list(plan.get("external") or []),
        },
        "build": {
            "compiled_units": result.get("compiled_units"),
            "compile_errors": result.get("compile_errors") or [],
            "compiler_contract_violations": violations,
            "reconciliation": reconciliation,
            "execution": result.get("execution"),
        },
        "grants_execution_authority": False,
    }
    write_json(out / ".receipt" / "validation" / "cross-source-stock.v1.json", trial)
    return trial


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stock_root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = run(Path(args.stock_root), Path(args.out))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
