from __future__ import annotations

import json
from pathlib import Path

from insert.paths import COMPILED_ROOT
from insertc.analyze import analyze_source
from insertc.gather import batch_package_name, gather_py_with_skips
from insertc.transform import compile_source

OWNER = "insert"


def _tops(rel_files: list[str]) -> set[str]:
    tops: set[str] = set()
    for rel in rel_files:
        first = Path(rel).parts[0]
        tops.add(Path(first).stem if first.endswith(".py") else first)
    return tops


def _dotted(package: str, rel: str) -> str:
    no_ext = rel[:-3] if rel.endswith(".py") else rel
    return package + "." + no_ext.replace("/", ".").replace("\\", ".")


def default_out(name: str) -> Path:
    return COMPILED_ROOT / name


def compile_tree(root: Path, name: str, out: Path | None = None) -> dict:
    """Compile ingested .py files into a standalone project folder.

    Output lives outside insertc. Insert house loads the project; it does not
    transform source.
    """
    root = root.resolve()
    package = batch_package_name(name)
    dest = (out or default_out(name)).resolve()
    if dest.exists() and dest.is_file():
        raise SystemExit(f"compile out is a file: {dest}")

    files, skipped = gather_py_with_skips(root)
    if not files:
        raise SystemExit(f"no .py files to compile from {root}")

    if root.is_file():
        pairs = [(root, root.name)]
        origin_root = str(root.parent)
    else:
        pairs = [(path, path.relative_to(root).as_posix()) for path in files]
        origin_root = str(root)

    rels = [rel for _path, rel in pairs]
    tops = _tops(rels)
    src_pkg = dest / "src" / package
    src_pkg.mkdir(parents=True, exist_ok=True)
    (src_pkg / "__init__.py").write_text(
        f'INSERT_OWNER = "{OWNER}"\nINSERT_BATCH = {package!r}\n',
        encoding="utf-8",
    )

    units = []
    contracts = {}
    dependencies = {}
    tree_files = []

    for path, rel in pairs:
        insert_id = _dotted(package, rel)
        compiled = compile_source(
            path.read_text(encoding="utf-8", errors="replace"),
            package=package,
            tops=tops,
            origin=f"{origin_root}/{rel}" if not root.is_file() else str(path),
            insert_id=insert_id,
        )
        dest_file = src_pkg / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(compiled, encoding="utf-8")
        cursor = src_pkg
        for part in Path(rel).parts[:-1]:
            cursor = cursor / part
            init = cursor / "__init__.py"
            if not init.exists():
                init.write_text("# insert package\n", encoding="utf-8")

        analysis = analyze_source(compiled, insert_id=insert_id, package=package)
        contracts[insert_id] = {
            "classes": analysis["classes"],
            "functions": analysis["functions"],
        }
        dependencies[insert_id] = analysis["dependencies"]
        rel_out = f"src/{package}/{rel}"
        tree_files.append(rel_out)
        units.append({"id": insert_id, "origin": str(path), "rel": rel, "compiled": rel_out})

    manifest = {
        "name": name,
        "package": package,
        "owner": OWNER,
        "compiler": "insertc",
        "origin": origin_root,
        "project": str(dest),
        "units": units,
        "skipped": skipped,
    }
    structure = {
        "package": package,
        "project": str(dest),
        "files": tree_files,
    }

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (dest / "contracts.json").write_text(json.dumps(contracts, indent=2) + "\n", encoding="utf-8")
    (dest / "dependencies.json").write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8")
    (dest / "structure.json").write_text(json.dumps(structure, indent=2) + "\n", encoding="utf-8")
    (dest / "pyproject.toml").write_text(
        f'[project]\nname = "{package.replace("_", "-")}"\nversion = "0.1.0"\n'
        'description = "insertc compiled project"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (dest / "README.md").write_text(
        f"# {name}\n\nCompiled by insertc. Housed by insert. Not a source tree.\n"
        f"Package: `{package}`\nUnits: {len(units)}\n",
        encoding="utf-8",
    )
    return manifest
