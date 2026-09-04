from __future__ import annotations

import ast
from pathlib import Path


def _params(args: ast.arguments) -> list[str]:
    names = [a.arg for a in args.posonlyargs + args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
        left, right = test.left, test.comparators[0]
        names = []
        for side in (left, right):
            if isinstance(side, ast.Name) and side.id == "__name__":
                names.append("name")
            if isinstance(side, ast.Constant) and side.value == "__main__":
                names.append("main")
        return "name" in names and "main" in names
    return False


class DropMain(ast.NodeTransformer):
    def visit_If(self, node: ast.If):
        if _is_main_guard(node):
            return None
        return self.generic_visit(node)


def inspect_source(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "syntax_ok": False,
            "syntax_error": f"{exc.msg} (line {exc.lineno})",
            "has_main": False,
            "classes": [],
            "functions": [],
            "imports": [],
        }

    has_main = False
    classes: list[dict] = []
    functions: list[dict] = []
    imports: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.If) and _is_main_guard(node):
            has_main = True
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    methods.append({"name": item.name, "params": _params(item.args)})
            classes.append({"name": node.name, "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions.append({"name": node.name, "params": _params(node.args)})
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports.append(mod if mod else ".")

    return {
        "syntax_ok": True,
        "syntax_error": None,
        "has_main": has_main,
        "classes": classes,
        "functions": functions,
        "imports": imports,
    }


def strip_main(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    tree = DropMain().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def inspect_file(path: Path) -> dict:
    source = path.read_text(encoding="utf-8", errors="replace")
    info = inspect_source(source)
    info["stripped"] = strip_main(source) if info["syntax_ok"] else None
    return info
