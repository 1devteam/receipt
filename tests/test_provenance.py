import tempfile
import unittest
from pathlib import Path

from collector.collect import collect_to


class ProvenanceTests(unittest.TestCase):
    def test_direct_receipts_json_preserves_raw_and_normalized_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = root / "tree"
            tree.mkdir()
            original = "# exact source comment\n\ndef run( x ):\n    return x + 1\n"
            (tree / "unit.py").write_text(original, encoding="utf-8")

            receipts = root / "receipts.json"
            data = collect_to(tree, receipts)
            unit = data["files"][0]

            raw = root / unit["raw"]
            normalized = root / unit["normalized"]
            self.assertTrue(raw.is_file())
            self.assertTrue(normalized.is_file())
            self.assertEqual(raw.read_text(encoding="utf-8"), original)
            self.assertNotEqual(raw.read_bytes(), normalized.read_bytes())
            self.assertEqual(unit["source_sha256"], unit["sha256"])
            self.assertEqual(unit["copy"], unit["normalized"])


if __name__ == "__main__":
    unittest.main()
