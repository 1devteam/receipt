from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector.collect import collect_to
from common.io import read_json
from receipt_stock.bootstrap import bootstrap_stock
from receipt_stock.build import plan_stock, stack_stock
from receipt_stock.composite import StockCompositeError
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


def _source_entry(source_id: str, *, mount: str = "demo") -> dict:
    return {
        "id": source_id,
        "repository": f"example/{source_id}",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "subpath": f"src/{mount}",
        "mount": mount,
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
    assert planned["selection"]["source_ids"] == ["demo-core"]
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
    assert result["stock_composite"] is None
    assert result["execution"]["performed"] is False


def test_cross_source_composite_reclassifies_dependency_and_builds(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    (alpha / "app.py").write_text(
        "from beta import util\n\ndef run(value: str) -> str:\n    return util.clean(value)\n",
        encoding="utf-8",
    )
    (beta / "util.py").write_text(
        "def clean(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
    trees = {"alpha-pack": alpha, "beta-pack": beta}

    def local_collector(_spec: str, out: Path, **kwargs):
        return collect_to(
            trees[out.name],
            out,
            update=bool(kwargs.get("update")),
            force=bool(kwargs.get("force")),
        )

    stock_root = tmp_path / "stock"
    bootstrap_stock(
        stock_root,
        manifest_path=_manifest(
            tmp_path / "manifest.json",
            [
                _source_entry("alpha-pack", mount="alpha"),
                _source_entry("beta-pack", mount="beta"),
            ],
        ),
        collector=local_collector,
    )
    units = load_unit_index(stock_root)["units"]
    alpha_unit = next(unit for unit in units if unit["rel"] == "alpha/app.py")
    beta_unit = next(unit for unit in units if unit["rel"] == "beta/util.py")

    isolated_alpha = read_json(stock_root / "catalogs" / "alpha-pack" / "receipts.json")
    isolated_app = next(rec for rec in isolated_alpha["files"] if rec["rel"] == "alpha/app.py")
    assert "beta" in isolated_app["dependencies"]["external"]

    planned = plan_stock(stock_root, [alpha_unit["id"], beta_unit["id"]])
    assert planned["selection"]["cross_source_compilation"] is True
    assert planned["selection"]["license_compatibility_not_determined"] is True
    assert planned["composite"]["schema"] == "receipt.stock.composite.v1"
    assert planned["plan"]["missing_local"] == []
    assert planned["plan"]["ambiguous_local"] == []
    assert planned["plan"]["count"] == 2

    composite_receipts = read_json(Path(planned["catalog"]) / "receipts.json")
    composite_app = next(rec for rec in composite_receipts["files"] if rec["rel"] == "alpha/app.py")
    assert "beta.util" in composite_app["dependencies"]["local"]
    assert "beta" not in composite_app["dependencies"]["external"]

    out = tmp_path / "built-composite"
    result = stack_stock(
        stock_root,
        [alpha_unit["id"], beta_unit["id"]],
        name="cross_stock",
        out=out,
    )
    assert result["compiled_units"] == 2
    assert result["graft_reconciliation"]["status"] == "reconciled"
    assert result["execution"]["performed"] is False
    assert result["stock_composite"]["source_ids"] == ["alpha-pack", "beta-pack"]
    assert result["stock_composite"]["license_compatibility_not_determined"] is True
    assert (out / ".receipt" / "stock" / "selection.v1.json").is_file()
    assert (out / ".receipt" / "stock" / "composite.v1.json").is_file()


def test_cross_source_composite_refuses_logical_path_collision(tmp_path: Path) -> None:
    trees: dict[str, Path] = {}
    for source_id, value in (("left", "LEFT"), ("right", "RIGHT")):
        tree = tmp_path / source_id
        tree.mkdir()
        (tree / "unit.py").write_text(
            f"def value() -> str:\n    return {value!r}\n",
            encoding="utf-8",
        )
        trees[source_id] = tree

    def local_collector(_spec: str, out: Path, **kwargs):
        return collect_to(trees[out.name], out, force=True)

    stock_root = tmp_path / "stock"
    bootstrap_stock(
        stock_root,
        manifest_path=_manifest(
            tmp_path / "manifest.json",
            [
                _source_entry("left", mount="shared"),
                _source_entry("right", mount="shared"),
            ],
        ),
        collector=local_collector,
    )
    units = load_unit_index(stock_root)["units"]
    left = next(unit for unit in units if unit["source_id"] == "left")
    right = next(unit for unit in units if unit["source_id"] == "right")

    with pytest.raises(StockCompositeError, match="logical path collisions"):
        plan_stock(stock_root, [left["id"], right["id"]])
