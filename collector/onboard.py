"""Onboard a .py unit: strip shelf noise; extract contracts + deps + topology (do not delete APIs)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path, PurePosixPath

from collector.inspect import DropMain, inspect_source

OWNER_NAMES = {
    "INSERT_OWNER",
    "INSERT_ORIGIN",
    "INSERT_ID",
    "INSERT_BATCH",
    "RECEIPT_OWNER",
    "RECEIPT_ORIGIN",
    "RECEIPT_ID",
    "RECEIPT_BATCH",
}

HEADER_PREFIXES = (
    "# insert-owned",
    "# receipt-owned",
    "# origin:",
    "# id:",
)

COMMON_SOURCE_ROOTS = {"src", "lib"}


class DropOwnerStamps(ast.NodeTransformer):
    """Remove module-level ownership stamp assignments only."""

    def visit_Assign(self, node: ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in OWNER_NAMES:
                return None
        if node.targets and all(
            isinstance(t, ast.Name) and t.id in OWNER_NAMES for t in node.targets
        ):
            return None
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.target.id in OWNER_NAMES:
            return None
        return self.generic_visit(node)


def _strip_header_comments(source: str) -> str:
    lines = source.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if not stripped:
            i += 1
            continue
        if any(stripped.startswith(p) for p in HEADER_PREFIXES):
            i += 1
            continue
        break
    return "".join(lines[i:])


def _had_owner_noise(source: str) -> bool:
    if any(name in source for name in OWNER_NAMES):
        return True
    for line in source.splitlines()[:8]:
        s = line.lstrip()
        if any(s.startswith(p) for p in HEADER_PREFIXES):
            return True
    return False


def strip_for_shelf(source: str) -> str | None:
    """Shelf copy: drop __main__ + ownership stamps/headers. Keep APIs and imports."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    tree = DropMain().visit(tree)
    tree = DropOwnerStamps().visit(tree)
    ast.fix_missing_locations(tree)
    body = ast.unparse(tree) + "\n"
    return _strip_header_comments(body)


def extract_contracts(info: dict) -> dict:
    """Lift source-backed public contracts from inspect output."""
    return {
        "classes": list(info.get("classes") or []),
        "functions": list(info.get("functions") or []),
    }


def extract_topology(info: dict) -> dict:
    """Lift syntactic behavioral facts without assigning application meaning."""
    raw = info.get("topology") if isinstance(info.get("topology"), dict) else {}
    return {
        "import_bindings": list(raw.get("import_bindings") or []),
        "calls": list(raw.get("calls") or []),
        "inheritance": list(raw.get("inheritance") or []),
        "dynamic_imports": list(raw.get("dynamic_imports") or []),
        "environment_reads": list(raw.get("environment_reads") or []),
        "effects": list(raw.get("effects") or []),
    }


def _is_local_absolute(module: str, local_modules: set[str]) -> bool:
    if not module:
        return False
    return any(
        known == module
        or known.startswith(module + ".")
        or module.startswith(known + ".")
        for known in local_modules
    )


def extract_dependencies(
    imports: list[str],
    tops: set[str],
    local_modules: set[str] | None = None,
) -> dict:
    """Classify imports. Code keeps imports; this is the sidecar map."""
    std = set(sys.stdlib_module_names)
    local: set[str] = set()
    external: set[str] = set()
    relative: set[str] = set()
    stdlib: set[str] = set()
    known_modules = local_modules or set()

    for raw in imports or []:
        if not raw or raw == "." or raw.startswith("."):
            relative.add(raw or ".")
            continue
        root = raw.split(".", 1)[0]
        if root in tops or _is_local_absolute(raw, known_modules):
            local.add(raw)
        elif root in std or root.startswith("_"):
            stdlib.add(root)
        else:
            external.add(raw)

    return {
        "local": sorted(local),
        "external": sorted(external),
        "relative": sorted(relative),
        "stdlib": sorted(stdlib),
    }


def tops_from_rels(rels: list[str]) -> set[str]:
    tops: set[str] = set()
    for rel in rels:
        first = Path(rel).parts[0]
        tops.add(Path(first).stem if first.endswith(".py") else first)
    return tops


def modules_from_rels(rels: list[str]) -> set[str]:
    """Return plausible importable module names for collected Python paths."""
    modules: set[str] = set()
    for rel in rels:
        parts = list(PurePosixPath(rel).parts)
        if not parts or not parts[-1].endswith(".py"):
            continue
        stem = Path(parts[-1]).stem
        module_parts = parts[:-1] if stem == "__init__" else [*parts[:-1], stem]
        if module_parts:
            modules.add(".".join(module_parts))
        if module_parts and module_parts[0] in COMMON_SOURCE_ROOTS and len(module_parts) > 1:
            modules.add(".".join(module_parts[1:]))
    return modules


def _normalization_transforms(source: str, info: dict) -> list[str]:
    if not info.get("syntax_ok"):
        return []
    transforms = ["ast_unparse_normalize"]
    if info.get("has_main"):
        transforms.append("remove_main_guard")
    if _had_owner_noise(source):
        transforms.append("remove_ownership_metadata")
    return transforms


def onboard_source(
    source: str,
    *,
    tops: set[str],
    local_modules: set[str] | None = None,
) -> dict:
    info = inspect_source(source)
    contracts = extract_contracts(info)
    topology = extract_topology(info)
    dependencies = extract_dependencies(
        info.get("imports") or [],
        tops,
        local_modules=local_modules,
    )
    stripped = strip_for_shelf(source) if info["syntax_ok"] else None
    owner_noise = _had_owner_noise(source)
    return {
        **info,
        "contracts": contracts,
        "dependencies": dependencies,
        "topology": topology,
        "stripped": stripped,
        "normalization_transforms": _normalization_transforms(source, info),
        "ownership_stripped": bool(info.get("has_main") or owner_noise),
    }


def onboard_file(
    path: Path,
    *,
    tops: set[str],
    local_modules: set[str] | None = None,
) -> dict:
    source = path.read_text(encoding="utf-8", errors="replace")
    return onboard_source(source, tops=tops, local_modules=local_modules)
