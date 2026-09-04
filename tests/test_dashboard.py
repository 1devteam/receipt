import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from http.server import ThreadingHTTPServer  # noqa: E402

from collector.collect import collect_to  # noqa: E402
from receipt_cli.dashboard.server import DashboardHandler  # noqa: E402


def _http_json(url: str, payload: dict | None = None) -> dict:
    if payload is None:
        with urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


class DashboardTests(unittest.TestCase):
    def test_api_browse_plan_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fixtures = ROOT / "tests" / "fixtures"
            shelves = tmp_path / "shelves"
            catalog = shelves / "demo"
            collect_to(fixtures, catalog)
            out = tmp_path / "stacked"

            DashboardHandler.catalogs_root = shelves
            DashboardHandler.default_catalog_path = catalog
            server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{port}"
            try:
                health = _http_json(f"{base}/health")
                self.assertTrue(health["ok"])

                with urlopen(f"{base}/", timeout=5) as resp:
                    html = resp.read().decode("utf-8")
                self.assertIn("Receipt", html)
                self.assertIn("stackForce", html)
                self.assertIn("collectUpdate", html)
                self.assertIn("/api/copy", html)
                self.assertIn("/api/collect", html)
                self.assertIn("/api/sync", html)

                cats = _http_json(f"{base}/api/catalogs")
                self.assertEqual(len(cats["catalogs"]), 1)

                listed = _http_json(
                    f"{base}/api/list?catalog={catalog}&query=alpha"
                )
                self.assertEqual(listed["count"], 1)

                shown = _http_json(
                    f"{base}/api/show?catalog={catalog}&key=alpha.py"
                )
                self.assertEqual(shown["rel"], "alpha.py")
                self.assertIn("contracts", shown)

                copied = _http_json(
                    f"{base}/api/copy?catalog={catalog}&key=alpha.py"
                )
                self.assertIn("class Alpha", copied["source"])
                self.assertEqual(copied["rel"], "alpha.py")

                planned = _http_json(
                    f"{base}/api/plan",
                    {"catalog": str(catalog), "seeds": ["alpha.py"]},
                )
                self.assertEqual(planned["count"], 2)

                stacked = _http_json(
                    f"{base}/api/stack",
                    {
                        "catalog": str(catalog),
                        "seeds": ["alpha.py"],
                        "name": "ui",
                        "out": str(out),
                    },
                )
                self.assertEqual(stacked["compiled_units"], 2)
                self.assertTrue(stacked["roster"]["ready"])
                self.assertTrue((out / "src" / "i_ui" / "alpha.py").is_file())

                try:
                    _http_json(f"{base}/api/show?catalog={catalog}&key=missing-nope")
                    self.fail("expected HTTPError")
                except HTTPError as exc:
                    self.assertEqual(exc.code, 400)
            finally:
                server.shutdown()
                server.server_close()

    def test_api_collect_and_stack_force_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shelves = tmp_path / "shelves"
            shelves.mkdir()
            tree = tmp_path / "tree"
            tree.mkdir()
            (tree / "solo.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            catalog = shelves / "from_api"

            DashboardHandler.catalogs_root = shelves
            DashboardHandler.default_catalog_path = None
            server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{port}"
            try:
                collected = _http_json(
                    f"{base}/api/collect",
                    {"tree": str(tree), "out": str(catalog)},
                )
                self.assertEqual(collected["files"], 1)
                self.assertTrue((catalog / "receipts.json").is_file())

                cats = _http_json(f"{base}/api/catalogs")
                self.assertEqual(len(cats["catalogs"]), 1)

                # Inject a missing local dep into the catalog receipts.
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
                        sidecar.write_text(
                            json.dumps(side, indent=2) + "\n", encoding="utf-8"
                        )
                receipts_path.write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )

                out = tmp_path / "stacked"
                try:
                    _http_json(
                        f"{base}/api/stack",
                        {
                            "catalog": str(catalog),
                            "seeds": ["solo.py"],
                            "name": "gap",
                            "out": str(out),
                            "force": False,
                        },
                    )
                    self.fail("expected HTTPError for gapped stack")
                except HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    body = json.loads(exc.read().decode("utf-8"))
                    self.assertIn("unresolved local deps", body["error"])

                forced = _http_json(
                    f"{base}/api/stack",
                    {
                        "catalog": str(catalog),
                        "seeds": ["solo.py"],
                        "name": "gap",
                        "out": str(out),
                        "force": True,
                        "check": False,
                    },
                )
                self.assertEqual(forced["compiled_units"], 1)
                self.assertTrue((out / "src" / "i_gap" / "solo.py").is_file())
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
