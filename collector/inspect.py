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


def _annotation(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _expr_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expr_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _decorators(nodes: list[ast.expr]) -> list[str]:
    return [name for name in (_expr_name(node) for node in nodes) if name]


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


def _import_from_names(node: ast.ImportFrom) -> list[str]:
    """Return import dependency names while preserving relative-import depth."""
    prefix = "." * int(node.level or 0)
    if node.module:
        return [prefix + node.module]
    if node.level:
        names = [prefix + alias.name for alias in node.names if alias.name != "*"]
        return names or [prefix]
    return []


def _import_bindings(tree: ast.AST) -> list[dict]:
    bindings: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                binding = alias.asname or alias.name.split(".", 1)[0]
                target = alias.name if alias.asname else binding
                bindings.append(
                    {
                        "binding": binding,
                        "target": target,
                        "kind": "import",
                        "line": getattr(node, "lineno", None),
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * int(node.level or 0)
            module = prefix + (node.module or "")
            for alias in node.names:
                if alias.name == "*":
                    continue
                target = f"{module}.{alias.name}" if module else alias.name
                bindings.append(
                    {
                        "binding": alias.asname or alias.name,
                        "target": target,
                        "kind": "from_import",
                        "line": getattr(node, "lineno", None),
                    }
                )
    return sorted(
        bindings,
        key=lambda item: (
            str(item.get("binding") or ""),
            str(item.get("target") or ""),
            int(item.get("line") or 0),
        ),
    )


def _calls(tree: ast.AST) -> list[dict]:
    calls: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _expr_name(node.func)
        if not target:
            continue
        calls.append(
            {
                "target": target,
                "line": getattr(node, "lineno", None),
                "arg_count": len(node.args),
                "keyword_names": sorted(
                    kw.arg for kw in node.keywords if isinstance(kw.arg, str) and kw.arg
                ),
            }
        )
    return sorted(
        calls,
        key=lambda item: (str(item.get("target") or ""), int(item.get("line") or 0)),
    )


def _dynamic_imports(tree: ast.AST) -> list[dict]:
    rows: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _expr_name(node.func)
        if target not in {"importlib.import_module", "__import__"}:
            continue
        literal = None
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            literal = node.args[0].value
        rows.append(
            {
                "target": target,
                "module_literal": literal,
                "line": getattr(node, "lineno", None),
                "resolution": "literal" if literal else "runtime",
            }
        )
    return rows


def _environment_reads(tree: ast.AST) -> list[dict]:
    rows: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _expr_name(node.func) == "os.getenv":
            key = None
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                key = node.args[0].value
            rows.append({"api": "os.getenv", "key": key, "line": getattr(node, "lineno", None)})
        elif isinstance(node, ast.Subscript) and _expr_name(node.value) == "os.environ":
            key = None
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                key = node.slice.value
            rows.append({"api": "os.environ", "key": key, "line": getattr(node, "lineno", None)})
    return rows


def _effect_calls(calls: list[dict]) -> list[dict]:
    prefixes = {
        "filesystem": (
            "open",
            "Path.open",
            "Path.read_text",
            "Path.read_bytes",
            "Path.write_text",
            "Path.write_bytes",
            "shutil.",
        ),
        "process": ("subprocess.", "os.system", "os.exec", "os.spawn"),
        "network": ("requests.", "httpx.", "aiohttp.", "urllib.request.", "socket."),
        "database": ("sqlite3.connect", "sqlalchemy.", "psycopg.", "psycopg2."),
    }
    rows: list[dict] = []
    for call in calls:
        target = str(call.get("target") or "")
        for kind, needles in prefixes.items():
            if any(target == needle or target.startswith(needle) for needle in needles):
                rows.append(
                    {
                        "kind": kind,
                        "target": target,
                        "line": call.get("line"),
                        "evidence": "syntactic_call",
                    }
                )
                break
    return rows


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
            "topology": {
                "import_bindings": [],
                "calls": [],
                "inheritance": [],
                "dynamic_imports": [],
                "environment_reads": [],
                "effects": [],
            },
        }

    has_main = False
    classes: list[dict] = []
    functions: list[dict] = []
    inheritance: list[dict] = []

    # Contracts remain intentionally module-level. Nested functions/classes are
    # implementation details, not public receipt entry points.
    for node in tree.body:
        if isinstance(node, ast.If) and _is_main_guard(node):
            has_main = True
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = []
            bases = [name for name in (_expr_name(base) for base in node.bases) if name]
            for base in bases:
                inheritance.append(
                    {
                        "class": node.name,
                        "base": base,
                        "line": getattr(node, "lineno", None),
                    }
                )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    methods.append(
                        {
                            "name": item.name,
                            "params": _params(item.args),
                            "returns": _annotation(item.returns),
                            "decorators": _decorators(item.decorator_list),
                            "async": isinstance(item, ast.AsyncFunctionDef),
                        }
                    )
            classes.append(
                {
                    "name": node.name,
                    "methods": methods,
                    "bases": bases,
                    "decorators": _decorators(node.decorator_list),
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions.append(
                    {
                        "name": node.name,
                        "params": _params(node.args),
                        "returns": _annotation(node.returns),
                        "decorators": _decorators(node.decorator_list),
                        "async": isinstance(node, ast.AsyncFunctionDef),
                    }
                )

    # Dependency discovery is deliberately recursive. Imports inside functions,
    # TYPE_CHECKING blocks, conditionals, and try/except fallbacks still affect
    # the source unit's potential runtime/type-checking closure.
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(_import_from_names(node))

    calls = _calls(tree)
    return {
        "syntax_ok": True,
        "syntax_error": None,
        "has_main": has_main,
        "classes": classes,
        "functions": functions,
        "imports": imports,
        "topology": {
            "import_bindings": _import_bindings(tree),
            "calls": calls,
            "inheritance": inheritance,
            "dynamic_imports": _dynamic_imports(tree),
            "environment_reads": _environment_reads(tree),
            "effects": _effect_calls(calls),
        },
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
