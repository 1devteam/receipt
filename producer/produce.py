from __future__ import annotations

import shutil
import sys
from pathlib import Path

from common.io import ReceiptIOError, read_json, write_json


class ProduceError(ValueError):
    """Invalid compile staging."""


def _externals(dependencies: dict) -> list[str]:
    std = set(sys.stdlib_module_names)
    found: set[str] = set()
    for deps in dependencies.values():
        for name in deps.get("external") or []:
            root = name.split(".", 1)[0]
            if root in std or root.startswith("_"):
                continue
            found.add(root)
    return sorted(found)


def _validate_staging(compile_dir: Path) -> tuple[dict, dict, dict, dict]:
    required = ("meta.json", "contracts.json", "dependencies.json", "receipts.json")
    for name in required:
        path = compile_dir / name
        if not path.is_file():
            raise ProduceError(f"invalid staging, missing {path}")

    try:
        meta = read_json(compile_dir / "meta.json")
        contracts = read_json(compile_dir / "contracts.json")
        dependencies = read_json(compile_dir / "dependencies.json")
        receipts = read_json(compile_dir / "receipts.json")
    except ReceiptIOError as exc:
        raise ProduceError(str(exc)) from exc

    if not isinstance(meta, dict) or "package" not in meta:
        raise ProduceError(f"meta.json missing package: {compile_dir / 'meta.json'}")
    units = meta.get("units")
    if not isinstance(units, list) or not units:
        raise ProduceError(f"meta.json has no units: {compile_dir / 'meta.json'}")

    modules = compile_dir / "modules"
    if not modules.is_dir():
        raise ProduceError(f"invalid staging, missing modules/: {modules}")

    for unit in units:
        if not isinstance(unit, dict) or "id" not in unit or "rel" not in unit:
            raise ProduceError(f"unit missing id/rel in {compile_dir / 'meta.json'}")
        src = modules / unit["rel"]
        if not src.is_file():
            raise ProduceError(f"missing module source: {src}")

    return meta, contracts, dependencies, receipts


def produce(compile_dir: Path, out: Path) -> dict:
    compile_dir = Path(compile_dir).resolve()
    out = Path(out).resolve()
    meta, contracts, dependencies, receipts = _validate_staging(compile_dir)

    package = meta["package"]
    src_pkg = out / "src" / package
    if src_pkg.exists():
        shutil.rmtree(src_pkg)
    src_pkg.mkdir(parents=True, exist_ok=True)
    (src_pkg / "__init__.py").write_text(
        f'RECEIPT_OWNER = "receipt"\nRECEIPT_BATCH = {package!r}\n',
        encoding="utf-8",
    )

    tree_files = []
    modules = compile_dir / "modules"
    for unit in meta["units"]:
        rel = unit["rel"]
        src = modules / rel
        dest = src_pkg / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        cursor = src_pkg
        for part in Path(rel).parts[:-1]:
            cursor = cursor / part
            init = cursor / "__init__.py"
            if not init.exists():
                init.write_text("# package\n", encoding="utf-8")
        tree_files.append(f"src/{package}/{rel}")

    reqs = _externals(dependencies)
    structure = {"package": package, "project": str(out), "files": tree_files}
    project_meta = {
        **meta,
        "project": str(out),
        "producer": "produce",
        "owner": meta.get("owner") or "receipt",
    }

    write_json(out / "manifest.json", project_meta)
    write_json(out / "contracts.json", contracts)
    write_json(out / "dependencies.json", dependencies)
    write_json(out / "structure.json", structure)
    write_json(out / "receipts.json", receipts)
    (out / "requirements.txt").write_text(
        "".join(f"{n}\n" for n in reqs) if reqs else "# no third-party imports detected\n",
        encoding="utf-8",
    )
    dist_name = package.replace("_", "-")
    (out / "pyproject.toml").write_text(
        "\n".join(
            [
                "[build-system]",
                'requires = ["setuptools>=68"]',
                'build-backend = "setuptools.build_meta"',
                "",
                "[project]",
                f'name = "{dist_name}"',
                'version = "0.1.0"',
                'requires-python = ">=3.11"',
                f'description = "Receipt-produced stack: {meta.get("name", package)}"',
                "",
                "[tool.setuptools.packages.find]",
                'where = ["src"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (out / "README.md").write_text(
        f"# {meta['name']}\n\nProduced by Receipt. Package `{package}`. Units: {len(meta['units'])}.\n\n"
        f"Install: `pip install -e .` from this folder (imports from `{package}`).\n"
        "Check: `direct check .` then `direct call . <unit_id> <target> [args…]`.\n",
        encoding="utf-8",
    )
    return project_meta
