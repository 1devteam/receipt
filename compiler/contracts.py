from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any


def validate_inventory(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    rels: dict[str, int] = {}
    module_shapes: set[str] = set()
    package_shapes: set[str] = set()

    for rec in files:
        rel = str(rec.get("rel") or "")
        if not rel:
            violations.append({"kind": "missing_rel"})
            continue
        rels[rel] = rels.get(rel, 0) + 1
        path = PurePosixPath(rel)
        if path.name == "__init__.py":
            package_shapes.add(str(path.parent))
        elif path.suffix == ".py":
            module_shapes.add(str(path.with_suffix("")))

    for rel, count in sorted(rels.items()):
        if count > 1:
            violations.append({"kind": "duplicate_output_path", "rel": rel, "count": count})
    for collision in sorted(module_shapes & package_shapes):
        violations.append({"kind": "module_package_collision", "module": collision})
    return violations


def validate_source_identity(rec: dict[str, Any], normalized_text: str) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    expected = rec.get("normalized_sha256")
    if expected:
        actual = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        if actual != expected:
            violations.append(
                {
                    "kind": "normalized_source_identity_mismatch",
                    "rel": rec.get("rel"),
                    "expected": expected,
                    "actual": actual,
                }
            )
    return violations


def validate_compiled_unit(
    *,
    rel: str,
    input_contracts: dict[str, list[str]],
    output_contracts: dict[str, list[str]],
    transforms: list[dict[str, Any]],
    input_dependencies: dict[str, Any],
    output_dependencies: dict[str, Any],
    package: str,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if input_contracts != output_contracts:
        violations.append(
            {
                "kind": "public_contract_changed",
                "rel": rel,
                "input": input_contracts,
                "output": output_contracts,
            }
        )

    rewrite_targets = {
        str(row.get("to"))
        for row in transforms
        if isinstance(row, dict)
        and row.get("kind") in {"rewrite_import", "rewrite_from_import"}
        and row.get("to")
    }
    output_local = set(output_dependencies.get("local") or [])
    unexplained = sorted(
        dep
        for dep in output_local
        if dep.startswith(package + ".") and dep not in rewrite_targets
    )
    if unexplained:
        # A rewritten parent import can legitimately account for child modules imported
        # by name, so only flag when no recorded rewrite is a prefix relationship.
        unexplained = [
            dep
            for dep in unexplained
            if not any(dep == target or dep.startswith(target + ".") or target.startswith(dep + ".") for target in rewrite_targets)
        ]
    if unexplained:
        violations.append(
            {
                "kind": "unexplained_dependency_change",
                "rel": rel,
                "dependencies": unexplained,
                "input_dependencies": input_dependencies,
            }
        )
    return violations
