import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.cli import main as collect_main  # noqa: E402
from collector.collect import CollectError, collect_to  # noqa: E402
from common.refuse import refused  # noqa: E402
from compiler.cli import main as compile_main  # noqa: E402
from compiler.compile import compile_receipts  # noqa: E402
from director.call import CallError, call_unit  # noqa: E402
from director.check import check_project  # noqa: E402
from director.cli import main as direct_main  # noqa: E402
from producer.cli import main as produce_main  # noqa: E402
from producer.produce import ProduceError, produce  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_four_systems(self):
        fixtures = ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipts = tmp_path / "receipts.json"
            staging = tmp_path / "compile"
            project = tmp_path / "project"
            data = collect_to(fixtures, receipts)
            self.assertEqual({f["rel"] for f in data["files"]}, {"alpha.py", "beta.py"})
            self.assertTrue(data["files"][0]["sha256"])
            alpha = next(f for f in data["files"] if f["rel"] == "alpha.py")
            self.assertTrue(alpha["syntax_ok"])
            self.assertTrue(alpha["has_main"])
            self.assertEqual(alpha["classes"][0]["name"], "Alpha")
            meta = compile_receipts(receipts, "pipe", staging)
            self.assertEqual(meta["package"], "i_pipe")
            self.assertEqual(meta["owner"], "receipt")
            self.assertEqual(len(meta["units"]), 2)
            produce(staging, project)
            init = (project / "src" / "i_pipe" / "__init__.py").read_text()
            self.assertIn("RECEIPT_OWNER", init)
            self.assertTrue((project / "contracts.json").is_file())
            self.assertTrue((project / "src" / "i_pipe" / "alpha.py").is_file())
            alpha_src = (project / "src" / "i_pipe" / "alpha.py").read_text()
            self.assertIn("RECEIPT_OWNER", alpha_src)
            self.assertIn("receipt-owned", alpha_src)
            deps = json.loads((project / "dependencies.json").read_text())
            self.assertIn("i_pipe.beta", deps["i_pipe.alpha"]["local"])
            pyproject = (project / "pyproject.toml").read_text()
            self.assertIn("[build-system]", pyproject)
            self.assertIn('build-backend = "setuptools.build_meta"', pyproject)
            self.assertIn("[tool.setuptools.packages.find]", pyproject)
            self.assertIn('where = ["src"]', pyproject)
            roster = check_project(project)
            self.assertTrue(roster["ready"])
            self.assertEqual(len(roster["ok"]), 2)
            self.assertEqual(
                call_unit(project, "i_pipe.alpha", "Alpha.greet", ["inmoa"]),
                "owned:hello inmoa",
            )

    def test_catalog_dir_strips_and_indexes(self):
        fixtures = ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog"
            data = collect_to(fixtures, catalog)
            self.assertTrue((catalog / "receipts.json").is_file())
            self.assertTrue((catalog / "index.json").is_file())
            alpha = next(f for f in data["files"] if f["rel"] == "alpha.py")
            copy = catalog / alpha["copy"]
            self.assertTrue(copy.is_file())
            text = copy.read_text()
            self.assertNotIn("__main__", text)
            self.assertIn("class Alpha", text)
            self.assertTrue((catalog / alpha["contracts_path"]).is_file())
            self.assertTrue((catalog / alpha["dependencies_path"]).is_file())
            contracts = json.loads((catalog / alpha["contracts_path"]).read_text())
            self.assertEqual(contracts["classes"][0]["name"], "Alpha")
            deps = json.loads((catalog / alpha["dependencies_path"]).read_text())
            self.assertIn("beta", deps["local"])
            self.assertEqual(alpha["contracts"]["classes"][0]["name"], "Alpha")
            index = json.loads((catalog / "index.json").read_text())
            self.assertIn("Alpha", index)
            self.assertIn("echo", index)
            from collector.find import find_symbol

            hits = find_symbol(catalog, "Alpha")
            self.assertEqual(hits[0]["symbol"], "Alpha")

    def test_collect_missing_tree_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope"
            with self.assertRaises(CollectError):
                collect_to(missing, Path(tmp) / "out.json")
            self.assertEqual(collect_main([str(missing), "-o", str(Path(tmp) / "out.json")]), 1)

    def test_onboard_strips_owner_keeps_api_extracts_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "unit.py").write_text(
                "# insert-owned by insert\n"
                "# origin: /old/path.py\n"
                "INSERT_OWNER = 'insert'\n"
                "INSERT_ID = 'i_old.unit'\n"
                "from helper import poke\n\n"
                "class Unit:\n"
                "    def run(self, x):\n"
                "        return poke(x)\n\n"
                "if __name__ == '__main__':\n"
                "    raise SystemExit(1)\n",
                encoding="utf-8",
            )
            (tree / "helper.py").write_text(
                "def poke(x):\n    return x\n",
                encoding="utf-8",
            )
            catalog = Path(tmp) / "catalog"
            data = collect_to(tree, catalog)
            unit = next(f for f in data["files"] if f["rel"] == "unit.py")
            copy = (catalog / unit["copy"]).read_text()
            self.assertNotIn("INSERT_OWNER", copy)
            self.assertNotIn("__main__", copy)
            self.assertIn("class Unit", copy)
            self.assertIn("from helper import poke", copy)
            self.assertTrue(unit["ownership_stripped"])
            self.assertEqual(unit["contracts"]["classes"][0]["name"], "Unit")
            self.assertIn("helper", unit["dependencies"]["local"])

    def test_refuse_skips_cache_and_build(self):
        self.assertEqual(refused(".pytest_cache/foo.py"), "vendor-or-cache")
        self.assertEqual(refused("dist/pkg.py"), "vendor-or-cache")
        self.assertEqual(refused("pkg.egg-info/foo.py"), "vendor-or-cache")
        self.assertIsNone(refused("src/app.py"))

    def test_compile_uses_catalog_copy_when_abs_gone(self):
        fixtures = ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog"
            staging = Path(tmp) / "compile"
            collect_to(fixtures, catalog)
            receipts_path = catalog / "receipts.json"
            data = json.loads(receipts_path.read_text())
            for rec in data["files"]:
                rec["abs"] = str(Path(tmp) / "deleted" / rec["rel"])
            receipts_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            meta = compile_receipts(receipts_path, "copy", staging)
            self.assertEqual(len(meta["units"]), 2)
            self.assertEqual(len(meta["errors"]), 0)
            self.assertEqual(compile_main([str(receipts_path), "--name", "copy", "-o", str(staging)]), 0)

    def test_produce_rejects_bad_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "staging"
            bad.mkdir()
            with self.assertRaises(ProduceError):
                produce(bad, Path(tmp) / "out")
            self.assertEqual(produce_main([str(bad), "-o", str(Path(tmp) / "out")]), 1)

    def test_direct_call_unknown_unit(self):
        fixtures = ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipts = tmp_path / "receipts.json"
            staging = tmp_path / "compile"
            project = tmp_path / "project"
            collect_to(fixtures, receipts)
            compile_receipts(receipts, "pipe", staging)
            produce(staging, project)
            with self.assertRaises(CallError):
                call_unit(project, "i_pipe.missing", "Alpha.greet", ["x"])
            self.assertEqual(
                direct_main(["call", str(project), "i_pipe.missing", "Alpha.greet", "x"]),
                1,
            )


if __name__ == "__main__":
    unittest.main()
