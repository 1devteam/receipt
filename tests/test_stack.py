import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.collect import collect_to  # noqa: E402
from receipt_cli.cli import main as receipt_main  # noqa: E402
from receipt_cli.stack import StackError, plan, stack  # noqa: E402


class StackTests(unittest.TestCase):
    def _catalog(self, tmp: Path) -> Path:
        fixtures = ROOT / "tests" / "fixtures"
        catalog = tmp / "catalog"
        collect_to(fixtures, catalog)
        return catalog

    def test_plan_closes_local_deps(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._catalog(Path(tmp))
            result = plan(catalog, ["alpha.py"])
            rels = {u["rel"] for u in result["units"]}
            self.assertEqual(rels, {"alpha.py", "beta.py"})
            self.assertEqual(result["seeds"], ["alpha.py"])
            self.assertFalse(result["missing_local"])
            self.assertFalse(result["ambiguous_local"])

    def test_stack_builds_runnable_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            catalog = self._catalog(tmp_path)
            out = tmp_path / "project"
            result = stack(catalog, ["Alpha"], name="demo", out=out)
            self.assertEqual(result["compiled_units"], 2)
            self.assertTrue(result["roster"]["ready"])
            self.assertTrue((out / "src" / "i_demo" / "alpha.py").is_file())
            self.assertTrue((out / "src" / "i_demo" / "beta.py").is_file())
            self.assertEqual(receipt_main(["plan", "alpha.py", "-c", str(catalog)]), 0)
            self.assertEqual(
                receipt_main(
                    [
                        "stack",
                        "beta.py",
                        "--name",
                        "solo",
                        "-o",
                        str(tmp_path / "solo"),
                        "-c",
                        str(catalog),
                    ]
                ),
                0,
            )

    def test_plan_closes_relative_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tree = tmp_path / "tree"
            pkg = tree / "pkg"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "b.py").write_text("VALUE = 7\n", encoding="utf-8")
            (pkg / "a.py").write_text(
                "from .b import VALUE\n\ndef read():\n    return VALUE\n",
                encoding="utf-8",
            )
            catalog = tmp_path / "catalog"
            collect_to(tree, catalog)

            planned = plan(catalog, ["pkg/a.py"])
            rels = {u["rel"] for u in planned["units"]}
            self.assertEqual(rels, {"pkg/a.py", "pkg/b.py"})
            self.assertFalse(planned["missing_local"])
            self.assertIn(".b", next(u for u in planned["units"] if u["rel"] == "pkg/a.py")["relative_deps"])

            out = tmp_path / "project"
            result = stack(catalog, ["pkg/a.py"], name="relative", out=out)
            self.assertEqual(result["compiled_units"], 2)
            self.assertTrue(result["roster"]["ready"])

    def test_from_dot_import_module_closes_relative_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tree = tmp_path / "tree"
            pkg = tree / "pkg"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "helper.py").write_text("VALUE = 3\n", encoding="utf-8")
            (pkg / "main.py").write_text(
                "from . import helper\n\ndef run():\n    return helper.VALUE\n",
                encoding="utf-8",
            )
            catalog = tmp_path / "catalog"
            data = collect_to(tree, catalog)
            main = next(f for f in data["files"] if f["rel"] == "pkg/main.py")
            self.assertIn(".helper", main["dependencies"]["relative"])

            planned = plan(catalog, ["pkg/main.py"])
            self.assertEqual(
                {u["rel"] for u in planned["units"]},
                {"pkg/helper.py", "pkg/main.py"},
            )

    def test_nested_imports_participate_in_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tree = tmp_path / "tree"
            tree.mkdir()
            (tree / "helper.py").write_text("VALUE = 11\n", encoding="utf-8")
            (tree / "main.py").write_text(
                "def run():\n    import helper\n    return helper.VALUE\n",
                encoding="utf-8",
            )
            catalog = tmp_path / "catalog"
            data = collect_to(tree, catalog)
            main = next(f for f in data["files"] if f["rel"] == "main.py")
            self.assertIn("helper", main["dependencies"]["local"])

            planned = plan(catalog, ["main.py"])
            self.assertEqual(
                {u["rel"] for u in planned["units"]},
                {"helper.py", "main.py"},
            )

    def test_src_layout_absolute_import_is_local_and_stackable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tree = tmp_path / "tree"
            pkg = tree / "src" / "acme"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "model.py").write_text(
                "class Model:\n    pass\n",
                encoding="utf-8",
            )
            (pkg / "service.py").write_text(
                "from acme.model import Model\n\ndef build():\n    return Model()\n",
                encoding="utf-8",
            )
            catalog = tmp_path / "catalog"
            data = collect_to(tree, catalog)
            service = next(f for f in data["files"] if f["rel"] == "src/acme/service.py")
            self.assertIn("acme.model", service["dependencies"]["local"])
            self.assertNotIn("acme.model", service["dependencies"]["external"])

            planned = plan(catalog, ["src/acme/service.py"])
            self.assertEqual(
                {u["rel"] for u in planned["units"]},
                {"src/acme/model.py", "src/acme/service.py"},
            )

            out = tmp_path / "project"
            result = stack(catalog, ["src/acme/service.py"], name="src_layout", out=out)
            self.assertTrue(result["roster"]["ready"])

    def test_ambiguous_seed_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tree = tmp_path / "tree"
            (tree / "a").mkdir(parents=True)
            (tree / "b").mkdir(parents=True)
            (tree / "a" / "dup.py").write_text("def one():\n    return 1\n", encoding="utf-8")
            (tree / "b" / "dup.py").write_text("def two():\n    return 2\n", encoding="utf-8")
            catalog = tmp_path / "catalog"
            collect_to(tree, catalog)
            with self.assertRaises(StackError):
                plan(catalog, ["dup.py"])

    def test_stack_refuses_missing_local_unless_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tree = tmp_path / "tree"
            tree.mkdir()
            (tree / "solo.py").write_text(
                "def run():\n    return 1\n",
                encoding="utf-8",
            )
            catalog = tmp_path / "catalog"
            collect_to(tree, catalog)

            receipts_path = catalog / "receipts.json"
            data = json.loads(receipts_path.read_text(encoding="utf-8"))
            solo = next(f for f in data["files"] if f["rel"] == "solo.py")
            deps = solo.setdefault("dependencies", {})
            deps["local"] = list(deps.get("local") or []) + ["missing_mod"]
            deps_path = solo.get("dependencies_path")
            if deps_path:
                sidecar = catalog / deps_path
                if sidecar.is_file():
                    side = json.loads(sidecar.read_text(encoding="utf-8"))
                    side["local"] = list(side.get("local") or []) + ["missing_mod"]
                    sidecar.write_text(json.dumps(side, indent=2) + "\n", encoding="utf-8")
            receipts_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

            planned = plan(catalog, ["solo.py"])
            self.assertEqual(planned["count"], 1)
            self.assertTrue(planned["missing_local"])
            self.assertEqual(planned["missing_local"][0]["module"], "missing_mod")

            out = tmp_path / "project"
            with self.assertRaises(StackError) as ctx:
                stack(catalog, ["solo.py"], name="gapped", out=out)
            self.assertIn("unresolved local deps", str(ctx.exception))
            self.assertFalse(out.exists())

            forced = stack(
                catalog, ["solo.py"], name="gapped", out=out, force=True, check=False
            )
            self.assertEqual(forced["compiled_units"], 1)
            self.assertTrue((out / "src" / "i_gapped" / "solo.py").is_file())

            out2 = tmp_path / "project2"
            self.assertEqual(
                receipt_main(
                    [
                        "stack",
                        "solo.py",
                        "--name",
                        "gapped2",
                        "-o",
                        str(out2),
                        "-c",
                        str(catalog),
                        "--force",
                        "--no-check",
                    ]
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
