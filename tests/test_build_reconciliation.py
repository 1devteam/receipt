from __future__ import annotations

from pathlib import Path

from collector.collect import collect_to
from common.io import read_json
from receipt_cli.stack import stack


def test_stack_emits_build_manifest_and_reconciles_compiled_topology(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "tests").mkdir()

    (source / "pkg" / "core.py").write_text(
        "def core(value: str) -> str:\n    return value.upper()\n",
        encoding="utf-8",
    )
    (source / "pkg" / "service.py").write_text(
        "from pkg import core\n\n"
        "def run(value: str) -> str:\n"
        "    return core.core(value)\n",
        encoding="utf-8",
    )
    (source / "tests" / "test_service.py").write_text(
        "from pkg import service\n\n"
        "def test_run():\n"
        "    assert service.run('a') == 'A'\n",
        encoding="utf-8",
    )

    catalog = tmp_path / "catalog"
    collect_to(source, catalog)

    out = tmp_path / "built"
    result = stack(
        catalog,
        ["pkg/service.py"],
        name="demo",
        out=out,
        check=False,
    )

    build_manifest_path = out / ".receipt" / "compiler" / "build-manifest.v1.json"
    reconciliation_path = out / ".receipt" / "graft" / "build-reconciliation.v1.json"
    assert build_manifest_path.is_file()
    assert reconciliation_path.is_file()

    build_manifest = read_json(build_manifest_path)
    reconciliation = read_json(reconciliation_path)

    assert build_manifest["schema"] == "receipt.compiler.build.v1"
    assert build_manifest["invariants"]["produced_units"] == 2
    assert build_manifest["invariants"]["rejected_units"] == 0
    assert build_manifest["invariants"]["all_produced_contracts_preserved"] is True

    service = next(unit for unit in build_manifest["units"] if unit["rel"] == "pkg/service.py")
    rewrites = [
        row
        for row in service["transforms"]
        if row.get("kind") in {"rewrite_import", "rewrite_from_import"}
    ]
    assert any(row.get("from") == "pkg" and row.get("to") == "i_demo.pkg" for row in rewrites)
    assert service["source"]["source_sha256"]
    assert service["output"]["sha256"]

    assert reconciliation["schema"] == "receipt.graft.build_reconciliation.v1"
    assert reconciliation["status"] == "reconciled"
    assert reconciliation["divergences"] == []
    assert reconciliation["pre_build"]["affected_count"] >= 3
    assert reconciliation["compiler"]["produced_units"] == 2
    assert any(node["rel"] == "pkg/service.py" for node in reconciliation["post_build"]["nodes"])
    assert result["graft_reconciliation"]["status"] == "reconciled"
    assert result["graft_reconciliation"]["divergences"] == 0
    assert result["execution"]["performed"] is False
