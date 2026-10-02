from __future__ import annotations

import hashlib
from pathlib import Path

from common.io import ReceiptIOError, read_json, write_json
from common.names import batch_package_name
from compiler.analyze import analyze_source
from compiler.transform import compile_source

BUILD_MANIFEST_SCHEMA = "receipt.compiler.build.v1"


def _tops(rels: list[str]) -> set[str]:
    tops: set[str] = set()
    for rel in rels:
        first = Path(rel).parts[0]
        tops.add(Path(first).stem if first.endswith(".py") else first)
    return tops


def _dotted(package: str, rel: str) -> str:
    no_ext = rel[:-3] if rel.endswith(".py") else rel
    return package + "." + no_ext.replace("/", ".").replace("\\", ".")


def _resolve_source(rec: dict, receipts_path: Path, catalog_hint: Path | None) -> Path | None:
    """Prefer catalog copy (portable), then absolute origin path."""
    copy = rec.get("copy")
    if copy:
        candidates: list[Path] = []
        if catalog_hint is not None:
            candidates.append(catalog_hint / copy)
        candidates.append(receipts_path.parent / copy)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    abs_path = rec.get("abs")
    if abs_path:
        path = Path(abs_path)
        if path.is_file():
            return path
    return None


def _catalog_root(receipts: dict, receipts_path: Path) -> Path | None:
    catalog = receipts.get("catalog")
    if catalog:
        path = Path(catalog)
        if path.is_dir():
            return path
    parent = receipts_path.parent
    if (parent / "copies").is_dir() or (parent / "index.json").is_file():
        return parent
    return None


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _contract_names(contracts: dict | None) -> dict[str, list[str]]:
    contracts = contracts if isinstance(contracts, dict) else {}
    classes = sorted(
        str(item.get("name"))
        for item in contracts.get("classes") or []
        if isinstance(item, dict) and item.get("name")
    )
    functions = sorted(
        str(item.get("name"))
        for item in contracts.get("functions") or []
        if isinstance(item, dict) and item.get("name")
    )
    return {"classes": classes, "functions": functions}


def compile_receipts(receipts_path: Path, name: str, out: Path) -> dict:
    receipts_path = Path(receipts_path).resolve()
    try:
        receipts = read_json(receipts_path)
    except ReceiptIOError:
        raise

    if not isinstance(receipts, dict):
        raise SystemExit(f"receipts must be an object: {receipts_path}")
    if "root" not in receipts:
        raise SystemExit(f"receipts missing root: {receipts_path}")

    files = receipts.get("files") or []
    if not files:
        raise SystemExit(f"receipts.json has no files: {receipts_path}")

    package = batch_package_name(name)
    for rec in files:
        if "rel" not in rec:
            raise SystemExit(f"receipt entry missing rel: {receipts_path}")
        if not rec.get("copy") and not rec.get("abs"):
            raise SystemExit(f"receipt entry missing copy/abs for {rec.get('rel')}: {receipts_path}")

    rels = [f["rel"] for f in files]
    tops = _tops(rels)
    origin_root = receipts["root"]
    catalog_hint = _catalog_root(receipts, receipts_path)
    out = out.resolve()
    mod_root = out / "modules"
    mod_root.mkdir(parents=True, exist_ok=True)

    units = []
    build_units = []
    rejected = []
    contracts = {}
    dependencies = {}
    errors = []
    warnings = []

    for rec in files:
        rel = rec["rel"]
        unit_id = _dotted(package, rel)
        src_path = _resolve_source(rec, receipts_path, catalog_hint)
        if src_path is None:
            error = {
                "id": unit_id,
                "rel": rel,
                "error": f"missing source (copy={rec.get('copy')!r} abs={rec.get('abs')!r})",
            }
            errors.append(error)
            rejected.append({"id": unit_id, "rel": rel, "reason": "missing_source"})
            continue
        raw = src_path.read_text(encoding="utf-8", errors="replace")
        try:
            compiled, file_warnings = compile_source(
                raw,
                package=package,
                tops=tops,
                origin=f"{origin_root}/{rel}",
                unit_id=unit_id,
                rels=rels,
            )
        except SyntaxError as exc:
            errors.append({"id": unit_id, "rel": rel, "error": f"syntax: {exc}"})
            rejected.append({"id": unit_id, "rel": rel, "reason": "syntax_error"})
            continue
        if file_warnings.get("relative_imports"):
            warnings.append(
                {
                    "id": unit_id,
                    "rel": rel,
                    "warning": f"relative imports left untouched ({file_warnings['relative_imports']})",
                }
            )
        dest = mod_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(compiled, encoding="utf-8")
        analysis = analyze_source(compiled, insert_id=unit_id, package=package)
        contracts[unit_id] = {
            "classes": analysis["classes"],
            "functions": analysis["functions"],
        }
        dependencies[unit_id] = analysis["dependencies"]
        units.append(
            {
                "id": unit_id,
                "rel": rel,
                "origin": rec.get("abs") or str(src_path),
                "source": str(src_path),
                "sha256": rec.get("sha256"),
            }
        )

        input_contracts = _contract_names(rec.get("contracts"))
        output_contracts = _contract_names(contracts[unit_id])
        build_units.append(
            {
                "id": unit_id,
                "rel": rel,
                "status": "produced",
                "source": {
                    "source_sha256": rec.get("source_sha256") or rec.get("sha256"),
                    "normalized_sha256": rec.get("normalized_sha256"),
                },
                "output": {
                    "path": f"modules/{rel}",
                    "sha256": _sha_text(compiled),
                },
                "transforms": list(file_warnings.get("transforms") or []),
                "contracts": {
                    "input": input_contracts,
                    "output": output_contracts,
                    "preserved": input_contracts == output_contracts,
                },
                "dependencies": {
                    "input": rec.get("dependencies") or {},
                    "output": analysis["dependencies"],
                },
                "warnings": {
                    key: value
                    for key, value in file_warnings.items()
                    if key != "transforms"
                },
            }
        )

    build_manifest = {
        "schema": BUILD_MANIFEST_SCHEMA,
        "name": name,
        "package": package,
        "owner": "receipt",
        "compiler": "compile",
        "selection": receipts.get("selection") or {"count": len(files)},
        "units": build_units,
        "rejected": rejected,
        "warnings": warnings,
        "invariants": {
            "input_units": len(files),
            "produced_units": len(build_units),
            "rejected_units": len(rejected),
            "all_produced_contracts_preserved": all(
                bool(unit.get("contracts", {}).get("preserved")) for unit in build_units
            ),
            "grants_execution_authority": False,
        },
    }

    meta = {
        "name": name,
        "package": package,
        "owner": "receipt",
        "compiler": "compile",
        "origin": origin_root,
        "receipts": str(receipts_path),
        "units": units,
        "errors": errors,
        "warnings": warnings,
        "build_manifest": {
            "schema": BUILD_MANIFEST_SCHEMA,
            "path": "build-manifest.json",
            "produced_units": len(build_units),
            "rejected_units": len(rejected),
        },
    }
    write_json(out / "meta.json", meta)
    write_json(out / "contracts.json", contracts)
    write_json(out / "dependencies.json", dependencies)
    write_json(out / "receipts.json", receipts)
    write_json(out / "build-manifest.json", build_manifest)
    return meta
