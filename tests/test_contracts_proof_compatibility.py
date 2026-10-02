from __future__ import annotations

from pathlib import Path

import pytest

from collector.collect import collect_to
from common.io import read_json, write_json
from receipt_cli.stack import StackError, stack


def _tree(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "core.py").write_text(
        "import os\n\ndef core(value: str) -> str:\n    return os.getenv('MODE', value).upper()\n",
        encoding="utf-8",
    )
    (root / "pkg" / "service.py").write_text(
        "from pkg import core\n\ndef run(value: str) -> str:\n    return core.core(value)\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_service.py").write_text(
        "from pkg import service\n\ndef test_run():\n    assert service.run('a') == 'A'\n",
        encoding="utf-8",
    )


def test_stack_emits_proof_selection_and_compatibility(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _tree(source)
    catalog = tmp_path / "catalog"
    collect_to(source, catalog)
    out = tmp_path / "built"
    result = stack(catalog, ["pkg/service.py"], name="demo", out=out)

    proof = read_json(out / ".receipt" / "graft" / "proof-plan.v1.json")
    compatibility = read_json(out / ".receipt" / "graft" / "compatibility.v1.json")
    assert proof["schema"] == "receipt.graft.proof_plan.v1"
    assert any(row["rel"] == "tests/test_service.py" for row in proof["direct_tests"])
    assert compatibility["schema"] == "receipt.graft.compatibility.v1"
    core = next(row for row in compatibility["units"] if row["rel"] == "pkg/core.py")
    assert any(call["name"] == "core" and call["returns"] == "str" for call in core["callables"])
    assert core["environment_requirements"] == ["MODE"]
    assert result["compiler_contracts"]["violations"] == []
    assert result["graft_proof_plan"]["fingerprint"]
    assert result["graft_compatibility"]["fingerprint"]


def test_stack_refuses_normalized_source_identity_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _tree(source)
    catalog = tmp_path / "catalog"
    collect_to(source, catalog)
    receipts = read_json(catalog / "receipts.json")
    service = next(row for row in receipts["files"] if row["rel"] == "pkg/service.py")
    (catalog / service["copy"]).write_text("def tampered():\n    return 1\n", encoding="utf-8")
    with pytest.raises(StackError, match="compiler contract violations"):
        stack(catalog, ["pkg/service.py"], name="demo", out=tmp_path / "built", force=False)
