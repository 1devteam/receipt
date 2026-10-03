from __future__ import annotations

import json
from pathlib import Path

from collector.collect import collect_to
from common.io import read_json
from receipt_stock.bootstrap import bootstrap_stock
from receipt_stock.manifest import BOOTSTRAP_SCHEMA
from receipt_stock.query import load_unit_index


def test_bootstrap_mount_restores_flattened_package_root_and_local_imports(tmp_path: Path) -> None:
    package = tmp_path / "demo"
    package.mkdir()
    (package / "core.py").write_text(
        "def normalize(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
    (package / "service.py").write_text(
        "from demo import core\n\ndef run(value: str) -> str:\n    return core.normalize(value)\n",
        encoding="utf-8",
    )

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": BOOTSTRAP_SCHEMA,
                "name": "mounted-stock",
                "sources": [
                    {
                        "id": "demo-core",
                        "repository": "example/demo",
                        "commit": "0123456789abcdef0123456789abcdef01234567",
                        "subpath": "src/demo",
                        "mount": "demo",
                        "license": "MIT",
                        "capabilities": ["utility"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def flattened_collector(_spec: str, out: Path, **kwargs):
        # Deliberately collect the package directory itself, reproducing GitHub
        # subpath behavior where rel paths initially become core.py/service.py.
        return collect_to(
            package,
            out,
            update=bool(kwargs.get("update")),
            force=bool(kwargs.get("force")),
        )

    stock_root = tmp_path / "stock"
    bootstrap_stock(stock_root, manifest_path=manifest, collector=flattened_collector)

    catalog = stock_root / "catalogs" / "demo-core"
    receipts = read_json(catalog / "receipts.json")
    by_rel = {rec["rel"]: rec for rec in receipts["files"]}
    assert set(by_rel) == {"demo/core.py", "demo/service.py"}
    assert by_rel["demo/service.py"]["stock_original_rel"] == "service.py"
    assert "demo.core" in by_rel["demo/service.py"]["dependencies"]["local"]
    assert "demo" not in by_rel["demo/service.py"]["dependencies"]["external"]
    assert receipts["stock_mount"] == {
        "logical_root": "demo",
        "source_subpath": "src/demo",
        "preserves_import_identity": True,
    }

    units = load_unit_index(stock_root)["units"]
    service = next(unit for unit in units if unit["rel"] == "demo/service.py")
    assert service["mount"] == "demo"
    assert service["original_rel"] == "service.py"
    assert service["grants_execution_authority"] is False
