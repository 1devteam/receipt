from __future__ import annotations

import json
from pathlib import Path

from collector.collect import collect_to
from common.io import read_json
from receipt_stock.admission import evaluate_receipt
from receipt_stock.bootstrap import bootstrap_stock
from receipt_stock.manifest import BOOTSTRAP_SCHEMA, load_bootstrap_manifest
from receipt_stock.query import find_units, load_unit_index


def test_bundled_manifest_is_pinned_and_capability_labeled() -> None:
    manifest = load_bootstrap_manifest()
    assert manifest["schema"] == BOOTSTRAP_SCHEMA
    assert len(manifest["sources"]) >= 11
    assert len({source["id"] for source in manifest["sources"]}) == len(manifest["sources"])
    for source in manifest["sources"]:
        assert len(source["commit"]) >= 12
        assert "/" in source["repository"]
        assert source["subpath"]
        assert source["license"]
        assert source["capabilities"]


def test_admission_rejects_unproven_source_identity() -> None:
    admission = evaluate_receipt(
        {
            "syntax_ok": True,
            "source_sha256": "abc",
            "normalized_sha256": "def",
            "dependencies": {"local": [], "external": [], "relative": [], "stdlib": []},
            "topology": {},
            "contracts": {"classes": [], "functions": []},
        },
        source_tags=["utility"],
    )
    assert admission["decision"] == "rejected"
    assert "source_identity_missing" in admission["hard_failures"]
    assert "utility" in admission["capability_tags"]


def test_bootstrap_materializes_catalog_unit_index_and_query_without_execution(tmp_path: Path) -> None:
    source_tree = tmp_path / "source"
    package = source_tree / "demo"
    package.mkdir(parents=True)
    (package / "core.py").write_text(
        "import os\n\ndef read_name(value: str) -> str:\n    return os.getenv('DEMO_NAME', value)\n",
        encoding="utf-8",
    )
    (package / "service.py").write_text(
        "from demo import core\n\ndef run(value: str) -> str:\n    return core.read_name(value)\n",
        encoding="utf-8",
    )

    manifest_path = tmp_path / "bootstrap.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": BOOTSTRAP_SCHEMA,
                "name": "test-stock",
                "sources": [
                    {
                        "id": "demo-core",
                        "repository": "example/demo",
                        "commit": "0123456789abcdef0123456789abcdef01234567",
                        "subpath": "src/demo",
                        "license": "MIT",
                        "capabilities": ["configuration", "utility"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def local_collector(_spec: str, out: Path, **kwargs):
        return collect_to(
            source_tree,
            out,
            update=bool(kwargs.get("update")),
            force=bool(kwargs.get("force")),
        )

    stock_root = tmp_path / "stock"
    result = bootstrap_stock(
        stock_root,
        manifest_path=manifest_path,
        collector=local_collector,
    )

    assert result["schema"] == "receipt.stock.index.v1"
    assert result["totals"]["files"] == 2
    assert result["totals"]["rejected"] == 0
    assert result["grants_execution_authority"] is False
    assert result["fingerprint"]
    assert result["unit_index"]["units"] == 2
    assert result["unit_index"]["fingerprint"]
    assert "configuration" in result["capability_tags"]
    assert "environment" in result["capability_tags"]

    catalog = stock_root / "catalogs" / "demo-core"
    receipts = read_json(catalog / "receipts.json")
    assert (catalog / "admission.v1.json").is_file()
    assert (stock_root / "stock-index.v1.json").is_file()
    assert (stock_root / "stock-units.v1.json").is_file()
    assert (stock_root / "bootstrap-manifest.v1.json").is_file()
    for rec in receipts["files"]:
        stock = rec["stock"]
        assert stock["bootstrap_source_id"] == "demo-core"
        assert stock["license"] == "MIT"
        assert stock["admission"]["decision"] in {"accepted", "constrained"}
        assert stock["admission"]["grants_execution_authority"] is False

    unit_index = load_unit_index(stock_root)
    assert unit_index["schema"] == "receipt.stock.units.v1"
    assert unit_index["counts"]["units"] == 2
    assert unit_index["security"]["contains_machine_local_origin"] is False
    assert all(unit["grants_execution_authority"] is False for unit in unit_index["units"])
    assert all("origin" not in unit["source_identity"] for unit in unit_index["units"])
    assert str(source_tree) not in json.dumps(unit_index)

    symbol_hits = find_units(stock_root, query="read_name")
    assert len(symbol_hits) == 1
    assert symbol_hits[0]["rel"] == "demo/core.py"
    assert symbol_hits[0]["source_id"] == "demo-core"

    capability_hits = find_units(stock_root, capabilities=["configuration", "environment"])
    assert any(hit["rel"] == "demo/core.py" for hit in capability_hits)
    source_hits = find_units(stock_root, source_id="demo-core", decision="accepted")
    assert len(source_hits) == 2
