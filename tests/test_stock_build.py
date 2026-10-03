from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector.collect import collect_to
from common.io import read_json
from receipt_stock.bootstrap import bootstrap_stock
from receipt_stock.build import StockBuildError, plan_stock, stack_stock
from receipt_stock.manifest import BOOTSTRAP_SCHEMA
from receipt_stock.query import load_unit_index


def _manifest(path: Path, sources: list[dict]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": BOOTSTRAP_SCHEMA,
                "name": "stock-build-test",
                "sources": sources,
            }
        ),
        encoding="utf-8",
    )
    return path


def _source_entry(source_id: str) -> dict:
    return {
        "id": source_id,
        "repository": f"example/{source_id}",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "subpath": "src/demo",
        "license": "MIT",
        "capabilities": ["utility", "configuration"],
    }


def test_stock_unit_selection_plans_and_builds_through_existing_stack(tmp_path: Path) -> None:
    tree = tmp_path / "source"
    package = tree / "demo"
    package.mkdir(parents=True)
    (package / "core.py").write_text(
        "def normalize(value: str) -> str:\n    return value.strip().lower()\n",
        encoding="utf-8",
    )
    (package / "service.py").write_text(
        "from demo import core\n\ndef run(value: str) -> str:\n    return core.normalize(value)\n",
        encoding="utf-8",
    )

    def local_collector(_spec: str, out: Path, **kwargs):
        return collect_to(
            tree,
            out,
            update=bool(kwargs.get("update")),
            force=bool(kwargs.get("force")),
        )

    stock_root = tmp_path / "stock"
    bootstrap_stock(
        stock_root,
        manifest_path=_manifest(tmp_path / "manifest.json", [_source_entry("demo-core")]),
        collector=local_collector,
    )
    unit_index = load_unit_index(stock_root)
    service = next(unit for unit in unit_index["units"] if unit["rel"] == "demo/service.py")

    planned = plan_stock(stock_root, [service["id"]])
    assert planned["selection"]["schema"] == "receipt.stock.selection.v1"
    assert planned["selection"]["source_id"] == "demo-core"
    assert planned["selection"]["stock_index_fingerprint"] == unit_index["fingerprint"]
    assert planned["plan"]["count"] == 2
    assert planned["plan"]["missing_local"] == []
    assert planned["selection"]["grants_execution_authority"] is False

    out = tmp_path / "built"
    result = stack_stock(stock_root, [service["id"]], name="stock_demo", out=out)
    artifact = out / ".receipt" / "stock" / "selection.v1.json"
    assert artifact.is_file()
    selection = read_json(artifact)
    assert selection["fingerprint"] == result["stock_selection"]["fingerprint"]
    assert selection["selected_units"][0]["source_sha256"] == service["source_sha256"]
    assert result["compiled_units"] == 2
    assert result["graft_reconciliation"]["status"] == "reconciled"
    assert result["execution"]["performed"] is False


def test_stock_build_refuses_unproven_cross_source_compilation(tmp_path: Path) -> None:
    trees: dict[str, Path] = {}
    for source_id in ("alpha", "beta"):
        tree = tmp_path / source_id
        package = tree / source_id
        package.mkdir(parents=True)
        (package / "unit.py").write_text(
            f"def value() -> str:\n    return {source_id!r}\n",
            encoding="utf-8",
        )
        trees[source_id] = tree

    def local_collector(spec: str, out: Path, **kwargs):
        source_id = out.name
        return collect_to(
            trees[source_id],
            out,
            update=bool(kwargs.get("update")),
            force=bool(kwargs.get("force")),
        )

    stock_root = tmp_path / "stock"
    bootstrap_stock(
        stock_root,
        manifest_path=_manifest(
            tmp_path / "manifest.json",
            [_source_entry("alpha"), _source_entry("beta")],
        ),
        collector=local_collector,
    )
    units = load_unit_index(stock_root)["units"]
    alpha = next(unit for unit in units if unit["source_id"] == "alpha")
    beta = next(unit for unit in units if unit["source_id"] == "beta")

    with pytest.raises(StockBuildError, match="cross-source compilation is not admitted yet"):
        plan_stock(stock_root, [alpha["id"], beta["id"]])
