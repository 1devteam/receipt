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
    manifest.write_text(json.dumps({
        "schema": BOOTSTRAP_SCHEMA,
        "name": "mounted-stock",
        "sources": [{
            "id": "demo-core", "repository": "example/demo",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "subpath": "src/demo", "mount": "demo", "license": "MIT",
            "capabilities": ["utility"],
        }],
    }), encoding="utf-8")

    def flattened_collector(_spec: str, out: Path, **kwargs):
        return collect_to(package, out, update=bool(kwargs.get("update")), force=bool(kwargs.get("force")))

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
        "logical_root": "demo", "kind": "package", "source_subpath": "src/demo",
        "preserves_import_identity": True,
    }
    service = next(unit for unit in load_unit_index(stock_root)["units"] if unit["rel"] == "demo/service.py")
    assert service["mount"] == "demo"
    assert service["mount_kind"] == "package"
    assert service["original_rel"] == "service.py"
    assert service["grants_execution_authority"] is False


def test_single_module_mount_preserves_top_level_import_identity(tmp_path: Path) -> None:
    module = tmp_path / "typing_extensions.py"
    module.write_text(
        "class Protocol:\n    pass\n\ndef runtime_checkable(value):\n    return value\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest-module.json"
    manifest.write_text(json.dumps({
        "schema": BOOTSTRAP_SCHEMA,
        "name": "module-stock",
        "sources": [{
            "id": "typing-extensions", "repository": "python/typing_extensions",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "subpath": "src/typing_extensions.py", "mount": "typing_extensions",
            "mount_kind": "module", "license": "PSF-2.0",
            "capabilities": ["typing", "compatibility"],
        }],
    }), encoding="utf-8")

    def file_collector(_spec: str, out: Path, **kwargs):
        return collect_to(module, out, update=bool(kwargs.get("update")), force=bool(kwargs.get("force")))

    stock_root = tmp_path / "stock-module"
    bootstrap_stock(stock_root, manifest_path=manifest, collector=file_collector)
    receipts = read_json(stock_root / "catalogs" / "typing-extensions" / "receipts.json")
    assert [rec["rel"] for rec in receipts["files"]] == ["typing_extensions.py"]
    assert receipts["stock_mount"] == {
        "logical_root": "typing_extensions", "kind": "module",
        "source_subpath": "src/typing_extensions.py", "preserves_import_identity": True,
    }
    unit = load_unit_index(stock_root)["units"][0]
    assert unit["mount"] == "typing_extensions"
    assert unit["mount_kind"] == "module"
    assert unit["rel"] == "typing_extensions.py"
    assert unit["source_identity"]["path"] == "typing_extensions.py"
