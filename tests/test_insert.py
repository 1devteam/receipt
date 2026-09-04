import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from insert.host import call, exports  # noqa: E402
from insertc.analyze import analyze_source  # noqa: E402
from insertc.compile import compile_tree  # noqa: E402
from insertc.gather import gather_py  # noqa: E402
from insertc.refuse import refused  # noqa: E402
from insertc.transform import compile_source  # noqa: E402


class RefuseTests(unittest.TestCase):
    def test_fleet_refused(self):
        self.assertEqual(refused("FleetLauncher.py"), "refused-filename")

    def test_normal_kept(self):
        self.assertIsNone(refused("CoreStatus.py"))


class CompilerTests(unittest.TestCase):
    def test_strips_main_and_stamps_owner(self):
        src = 'from beta import echo\n\nif __name__ == "__main__":\n    print(1)\n'
        out = compile_source(
            src,
            package="i_fix",
            tops={"beta"},
            origin="/tmp/alpha.py",
            insert_id="i_fix.alpha",
        )
        tree = ast.parse(out)
        mains = [n for n in tree.body if isinstance(n, ast.If)]
        self.assertEqual(mains, [])
        self.assertIn("INSERT_OWNER", out)
        self.assertIn("i_fix.beta", out)

    def test_analyze_contract_and_deps(self):
        src = compile_source(
            "import time\nfrom beta import echo\n\nclass Alpha:\n    def greet(self, name):\n        return echo(name)\n",
            package="i_fix",
            tops={"beta"},
            origin="alpha.py",
            insert_id="i_fix.alpha",
        )
        info = analyze_source(src, insert_id="i_fix.alpha", package="i_fix")
        self.assertEqual(info["classes"][0]["name"], "Alpha")
        self.assertEqual(info["classes"][0]["methods"][0]["name"], "greet")
        self.assertIn("time", info["dependencies"]["external"])
        self.assertTrue(any(d.startswith("i_fix") for d in info["dependencies"]["local"]))


class PairTests(unittest.TestCase):
    def test_compiler_emits_own_project(self):
        fixtures = Path(__file__).parent / "fixtures"
        self.assertEqual({p.name for p in gather_py(fixtures)}, {"alpha.py", "beta.py"})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "pairfix"
            manifest = compile_tree(fixtures, "pairfix", out=dest)
            self.assertEqual(manifest["compiler"], "insertc")
            self.assertTrue((dest / "contracts.json").is_file())
            self.assertTrue((dest / "dependencies.json").is_file())
            self.assertTrue((dest / "structure.json").is_file())
            self.assertTrue((dest / "src" / "i_pairfix" / "alpha.py").is_file())
            self.assertFalse(str(dest).endswith("/insert/insertc"))
            contracts = json.loads((dest / "contracts.json").read_text())
            self.assertIn("Alpha", [c["name"] for c in contracts["i_pairfix.alpha"]["classes"]])
            deps = json.loads((dest / "dependencies.json").read_text())
            self.assertIn("i_pairfix.beta", deps["i_pairfix.alpha"]["local"])
            self.assertIn("Alpha", exports("i_pairfix.alpha", project=dest))
            self.assertEqual(
                call("i_pairfix.alpha", "Alpha.greet", ["world"], project=dest),
                "owned:hello world",
            )


if __name__ == "__main__":
    unittest.main()
