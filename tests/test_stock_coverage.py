from __future__ import annotations

from pathlib import Path

from common.io import write_json
from receipt_stock.coverage import STOCK_COVERAGE_SCHEMA, build_stock_coverage, write_stock_coverage
from receipt_stock.query import STOCK_UNITS_SCHEMA


def test_stock_coverage_distinguishes_available_stock_from_inventory_gaps(tmp_path: Path) -> None:
    root = tmp_path / "stock"
    root.mkdir()
    write_json(
        root / "stock-units.v1.json",
        {
            "schema": STOCK_UNITS_SCHEMA,
            "fingerprint": "unit-index-proof",
            "units": [
                {
                    "id": "fastapi:1",
                    "source_id": "fastapi-web",
                    "mount": "fastapi",
                    "external_dependencies": ["pydantic", "starlette.routing", "annotated_types"],
                },
                {
                    "id": "openai:1",
                    "source_id": "openai-sdk",
                    "mount": "openai",
                    "external_dependencies": ["httpx", "pydantic"],
                },
                {
                    "id": "pydantic:1",
                    "source_id": "pydantic-models",
                    "mount": "pydantic",
                    "external_dependencies": ["pydantic_core"],
                },
                {
                    "id": "starlette:1",
                    "source_id": "starlette-web-runtime",
                    "mount": "starlette",
                    "external_dependencies": ["anyio"],
                },
                {
                    "id": "httpx:1",
                    "source_id": "httpx-async-client",
                    "mount": "httpx",
                    "external_dependencies": ["httpcore"],
                },
            ],
        },
    )

    report = build_stock_coverage(root)
    assert report["schema"] == STOCK_COVERAGE_SCHEMA
    assert report["stock_unit_index_fingerprint"] == "unit-index-proof"
    joins = {
        (row["consumer_source"], row["provider_source"], row["package"])
        for row in report["latent_stock_joins"]
    }
    assert ("fastapi-web", "pydantic-models", "pydantic") in joins
    assert ("fastapi-web", "starlette-web-runtime", "starlette") in joins
    assert ("openai-sdk", "httpx-async-client", "httpx") in joins
    assert ("openai-sdk", "pydantic-models", "pydantic") in joins

    uncovered = {row["package"] for row in report["uncovered_external_packages"]}
    assert {"annotated_types", "pydantic_core", "anyio", "httpcore"} <= uncovered
    assert report["authority"] == {
        "selects_units": False,
        "asserts_api_compatibility": False,
        "asserts_version_compatibility": False,
        "asserts_license_compatibility": False,
        "grants_execution_authority": False,
    }
    assert report["fingerprint"]

    persisted = write_stock_coverage(root)
    assert persisted["fingerprint"] == report["fingerprint"]
    assert (root / "stock-coverage.v1.json").is_file()
