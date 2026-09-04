import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.cli import main as collect_main  # noqa: E402
from collector.collect import CollectError, collect_to  # noqa: E402
from collector.github import (  # noqa: E402
    GitHubError,
    GitHubSpec,
    is_github_spec,
    parse_github,
)
from compiler.compile import compile_receipts  # noqa: E402


def _tarball(files: dict[str, str], prefix: str = "owner-repo-deadbeef") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"{prefix}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeResp:
    def __init__(self, data: bytes, url: str = "https://codeload.github.com/o/r/legacy.tar.gz/main"):
        self._data = data
        self.url = url
        self.status = 200

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            out, self._data = self._data, b""
            return out
        out, self._data = self._data[:n], self._data[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ParseGitHubTests(unittest.TestCase):
    def test_urls_and_slugs(self):
        cases = [
            ("https://github.com/acme/tools", "acme", "tools", None, None),
            ("https://github.com/acme/tools.git", "acme", "tools", None, None),
            ("https://github.com/acme/tools/tree/main", "acme", "tools", "main", None),
            (
                "https://github.com/acme/tools/tree/main/src/pkg",
                "acme",
                "tools",
                "main",
                "src/pkg",
            ),
            (
                "https://github.com/acme/tools/blob/main/src/pkg/mod.py",
                "acme",
                "tools",
                "main",
                "src/pkg/mod.py",
            ),
            ("github:acme/tools@v1", "acme", "tools", "v1", None),
            ("github:acme/tools@v1:src", "acme", "tools", "v1", "src"),
            ("acme/tools", "acme", "tools", None, None),
            ("acme/tools@main", "acme", "tools", "main", None),
            ("git@github.com:acme/tools.git", "acme", "tools", None, None),
        ]
        for spec, owner, repo, ref, subpath in cases:
            parsed = parse_github(spec)
            self.assertEqual(parsed.owner, owner, spec)
            self.assertEqual(parsed.repo, repo, spec)
            self.assertEqual(parsed.ref, ref, spec)
            self.assertEqual(parsed.subpath, subpath, spec)

    def test_ref_flag_overrides(self):
        parsed = parse_github("https://github.com/acme/tools/tree/main", ref="v2")
        self.assertEqual(parsed.ref, "v2")

    def test_blob_kind(self):
        parsed = parse_github("https://github.com/acme/tools/blob/main/a.py")
        self.assertEqual(parsed.kind, "blob")
        self.assertEqual(
            parsed.blob_url("a.py"),
            "https://github.com/acme/tools/blob/main/a.py",
        )

    def test_local_path_is_not_github(self):
        fixtures = ROOT / "tests" / "fixtures"
        self.assertFalse(is_github_spec(str(fixtures)))
        self.assertTrue(is_github_spec("https://github.com/acme/tools"))
        self.assertTrue(is_github_spec("acme/tools"))
        self.assertFalse(is_github_spec("./acme/tools"))
        self.assertFalse(is_github_spec("/tmp/acme/tools"))

    def test_empty_spec(self):
        with self.assertRaises(GitHubError):
            parse_github("")


class FetchGitHubTests(unittest.TestCase):
    def test_collect_from_github_tarball(self):
        payload = _tarball(
            {
                "pkg/alpha.py": "def ping():\n    return 1\n",
                "pkg/beta.py": "from alpha import ping\n\ndef echo():\n    return ping()\n",
                "README.md": "nope\n",
                ".venv/lib/x.py": "ignored = 1\n",
            }
        )

        def fake_urlopen(req, timeout=0):
            self.assertIn("api.github.com/repos/acme/tools/tarball/main", req.full_url)
            self.assertEqual(req.get_header("User-agent"), "receipt-cli")
            return FakeResp(payload)

        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog"
            with patch("collector.github.urlopen", fake_urlopen):
                data = collect_to("https://github.com/acme/tools/tree/main", catalog)
            rels = {f["rel"] for f in data["files"]}
            self.assertEqual(rels, {"pkg/alpha.py", "pkg/beta.py"})
            self.assertEqual(data["source"]["kind"], "github")
            self.assertEqual(data["source"]["owner"], "acme")
            self.assertEqual(data["source"]["repo"], "tools")
            self.assertEqual(data["source"]["ref"], "main")
            self.assertTrue(data["root"].startswith("https://github.com/acme/tools"))
            alpha = next(f for f in data["files"] if f["rel"] == "pkg/alpha.py")
            self.assertEqual(
                alpha["abs"],
                "https://github.com/acme/tools/blob/main/pkg/alpha.py",
            )
            self.assertTrue((catalog / alpha["copy"]).is_file())
            meta = compile_receipts(catalog / "receipts.json", "gh", Path(tmp) / "compile")
            self.assertEqual(len(meta["units"]), 2)
            self.assertEqual(len(meta["errors"]), 0)

    def test_subpath_and_cli(self):
        payload = _tarball(
            {
                "src/pkg/mod.py": "class Mod:\n    def run(self):\n        return 1\n",
                "src/other.py": "x = 1\n",
                "root.py": "skip_me = 1\n",
            }
        )

        def fake_urlopen(req, timeout=0):
            self.assertIn("/tarball/v1", req.full_url)
            return FakeResp(payload)

        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "from-cli"
            with patch("collector.github.urlopen", fake_urlopen):
                code = collect_main(
                    ["github:acme/tools@v1:src", "-o", str(catalog)]
                )
            self.assertEqual(code, 0)
            receipts = json.loads((catalog / "receipts.json").read_text(encoding="utf-8"))
            rels = {f["rel"] for f in receipts["files"]}
            self.assertEqual(rels, {"pkg/mod.py", "other.py"})
            self.assertNotIn("root.py", rels)

    def test_missing_repo_is_collect_error(self):
        def fake_urlopen(req, timeout=0):
            raise HTTPError(req.full_url, 404, "Not Found", hdrs=None, fp=io.BytesIO())

        with tempfile.TemporaryDirectory() as tmp:
            with patch("collector.github.urlopen", fake_urlopen):
                with self.assertRaises(CollectError) as ctx:
                    collect_to("acme/missing", Path(tmp) / "out")
            self.assertIn("not found", str(ctx.exception))

    def test_json_out_still_keeps_copies_for_github(self):
        payload = _tarball({"solo.py": "def run():\n    return 1\n"})

        def fake_urlopen(req, timeout=0):
            return FakeResp(payload)

        with tempfile.TemporaryDirectory() as tmp:
            receipts = Path(tmp) / "receipts.json"
            with patch("collector.github.urlopen", fake_urlopen):
                data = collect_to("acme/tools", receipts, ref="HEAD")
            self.assertTrue((Path(tmp) / data["files"][0]["copy"]).is_file())
            meta = compile_receipts(receipts, "solo", Path(tmp) / "compile")
            self.assertEqual(len(meta["units"]), 1)

    def test_auth_header_when_token_set(self):
        payload = _tarball({"a.py": "n = 1\n"})
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["auth"] = req.get_header("Authorization")
            return FakeResp(payload)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GITHUB_TOKEN": "ghs_test"}, clear=False):
                with patch("collector.github.urlopen", fake_urlopen):
                    collect_to("acme/tools", Path(tmp) / "cat")
        self.assertEqual(seen["auth"], "Bearer ghs_test")

    def test_blob_file_only(self):
        payload = _tarball(
            {
                "src/keep.py": "def keep():\n    return 1\n",
                "src/skip.py": "def skip():\n    return 0\n",
            }
        )

        def fake_urlopen(req, timeout=0):
            return FakeResp(payload)

        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "blob"
            with patch("collector.github.urlopen", fake_urlopen):
                data = collect_to(
                    "https://github.com/acme/tools/blob/main/src/keep.py",
                    catalog,
                )
            self.assertEqual([f["rel"] for f in data["files"]], ["keep.py"])
            self.assertEqual(
                data["files"][0]["abs"],
                "https://github.com/acme/tools/blob/main/src/keep.py",
            )

    def test_spec_dataclass_urls(self):
        spec = GitHubSpec("acme", "tools", ref="main", subpath="src")
        self.assertEqual(spec.page_url(), "https://github.com/acme/tools/tree/main/src")
        self.assertEqual(
            spec.blob_url("pkg/a.py"),
            "https://github.com/acme/tools/blob/main/src/pkg/a.py",
        )


if __name__ == "__main__":
    unittest.main()
