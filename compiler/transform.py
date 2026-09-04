from __future__ import annotations

import ast

OWNER = "receipt"


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


def resolve_local(module: str, package: str, tops: set[str], rels: list[str]) -> str | None:
    if not module:
        return None
    root = module.split(".", 1)[0]
    if root in tops:
        return f"{package}.{module}"
    needle = module.replace(".", "/") + ".py"
    hits = [r for r in rels if r == needle or r.endswith("/" + needle)]
    if len(hits) == 1:
        return package + "." + hits[0][:-3].replace("/", ".")
    return None


class StripOwner(ast.NodeTransformer):
    def __init__(self, package: str, tops: set[str], rels: list[str]):
        self.package = package
        self.tops = tops
        self.rels = rels
        self.relative_imports = 0

    def visit_If(self, node: ast.If):
        if _is_main_guard(node):
            return None
        return self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        new_names: list[ast.alias] = []
        for alias in node.names:
            rewritten = resolve_local(alias.name, self.package, self.tops, self.rels)
            if rewritten:
                asname = alias.asname or alias.name.split(".", 1)[0]
                new_names.append(ast.alias(name=rewritten, asname=asname))
            else:
                new_names.append(alias)
        node.names = new_names
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level and node.level > 0:
            self.relative_imports += 1
            return node
        if not node.module:
            return node
        rewritten = resolve_local(node.module, self.package, self.tops, self.rels)
        if rewritten:
            node.module = rewritten
        return node


def _stamp(origin: str, unit_id: str) -> list[ast.stmt]:
    def assign(name: str, value: str) -> ast.Assign:
        return ast.Assign(
            targets=[ast.Name(id=name, ctx=ast.Store())],
            value=ast.Constant(value=value),
        )

    return [
        assign("RECEIPT_OWNER", OWNER),
        assign("RECEIPT_ORIGIN", origin),
        assign("RECEIPT_ID", unit_id),
    ]


def compile_source(
    source: str,
    *,
    package: str,
    tops: set[str],
    origin: str,
    unit_id: str,
    rels: list[str] | None = None,
) -> tuple[str, dict]:
    """Compile source. Returns (compiled_text, warnings)."""
    tree = ast.parse(source)
    transformer = StripOwner(package, tops, rels or [])
    tree = transformer.visit(tree)
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
    tree.body = ([docstring] if docstring else []) + _stamp(origin, unit_id) + rest
    ast.fix_missing_locations(tree)
    header = f"# receipt-owned by {OWNER}\n# origin: {origin}\n# id: {unit_id}\n"
    warnings: dict = {}
    if transformer.relative_imports:
        warnings["relative_imports"] = transformer.relative_imports
    return header + ast.unparse(tree) + "\n", warnings
