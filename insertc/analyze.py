from __future__ import annotations

import ast


def _params(args: ast.arguments) -> list[str]:
    names = [a.arg for a in args.posonlyargs + args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def _split_deps(module: str | None, package: str) -> tuple[str | None, str]:
    if not module:
        return None, "local"
    if module == package or module.startswith(package + "."):
        return module, "local"
    return module.split(".", 1)[0], "external"


def analyze_source(source: str, *, insert_id: str, package: str) -> dict:
    tree = ast.parse(source)
    classes: list[dict] = []
    functions: list[dict] = []
    local: set[str] = set()
    external: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    methods.append({"name": item.name, "params": _params(item.args)})
            classes.append({"name": node.name, "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            functions.append({"name": node.name, "params": _params(node.args)})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name, kind = _split_deps(alias.name, package)
                if name:
                    (local if kind == "local" else external).add(name)
        elif isinstance(node, ast.ImportFrom):
            name, kind = _split_deps(node.module, package)
            if name:
                (local if kind == "local" else external).add(name)

    return {
        "id": insert_id,
        "classes": classes,
        "functions": functions,
        "dependencies": {
            "local": sorted(local),
            "external": sorted(external),
        },
    }
