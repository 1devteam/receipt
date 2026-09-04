from __future__ import annotations

import ast
from pathlib import Path

OWNER = "insert"


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


class StripOwner(ast.NodeTransformer):
    def __init__(self, package: str, tops: set[str]):
        self.package = package
        self.tops = tops

    def visit_If(self, node: ast.If):
        if _is_main_guard(node):
            return None
        return self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        new_names: list[ast.alias] = []
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in self.tops:
                full = f"{self.package}.{alias.name}"
                asname = alias.asname or root
                new_names.append(ast.alias(name=full, asname=asname))
            else:
                new_names.append(alias)
        node.names = new_names
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level and node.level > 0:
            return node
        if not node.module:
            return node
        root = node.module.split(".", 1)[0]
        if root in self.tops:
            node.module = f"{self.package}.{node.module}"
        return node


def _stamp(origin: str, insert_id: str) -> list[ast.stmt]:
    def assign(name: str, value: str) -> ast.Assign:
        return ast.Assign(
            targets=[ast.Name(id=name, ctx=ast.Store())],
            value=ast.Constant(value=value),
        )

    return [
        assign("INSERT_OWNER", OWNER),
        assign("INSERT_ORIGIN", origin),
        assign("INSERT_ID", insert_id),
    ]


def compile_source(
    source: str,
    *,
    package: str,
    tops: set[str],
    origin: str,
    insert_id: str,
) -> str:
    tree = ast.parse(source)
    tree = StripOwner(package, tops).visit(tree)
    ast.fix_missing_locations(tree)

    body = list(tree.body)
    docstring = None
    rest = body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        docstring = body[0]
        rest = body[1:]
    tree.body = ([docstring] if docstring else []) + _stamp(origin, insert_id) + rest
    ast.fix_missing_locations(tree)
    header = f"# insert-owned by {OWNER}\n# origin: {origin}\n# id: {insert_id}\n"
    return header + ast.unparse(tree) + "\n"


def write_compiled(
    dest: Path,
    source: str,
    *,
    package: str,
    tops: set[str],
    origin: str,
    insert_id: str,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        compile_source(
            source,
            package=package,
            tops=tops,
            origin=origin,
            insert_id=insert_id,
        ),
        encoding="utf-8",
    )
