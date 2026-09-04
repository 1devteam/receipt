import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.collect import collect_to  # noqa: E402
from receipt_cli.cli import main as receipt_main  # noqa: E402
from receipt_cli.shelf import (  # noqa: E402
    ShelfError,
    catalog_summary,
    list_catalogs,
    list_receipts,
    search_symbols,
    show_receipt,
)


class ReceiptCliTests(unittest.TestCase):
    def test_shelf_browse_and_search(self):
        fixtures = ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "shelves" / "demo"
            collect_to(fixtures, catalog)

            cats = list_catalogs(root / "shelves")
            self.assertEqual(len(cats), 1)
            self.assertEqual(cats[0]["name"], "demo")
            self.assertEqual(cats[0]["files"], 2)

            summary = catalog_summary(catalog)
            self.assertEqual(summary["files"], 2)
            self.assertTrue(summary["has_index"])

            rows = list_receipts(catalog, query="alpha")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["rel"], "alpha.py")

            hits = search_symbols(catalog, "Alpha")
            self.assertEqual(hits[0]["symbol"], "Alpha")

            shown = show_receipt(catalog, "alpha.py")
            self.assertEqual(shown["rel"], "alpha.py")
            self.assertTrue(shown["copy_path"])
            self.assertEqual(shown["contracts"]["classes"][0]["name"], "Alpha")
            self.assertIn("beta", shown["dependencies"]["local"])

            # CLI surface
            self.assertEqual(
                receipt_main(["catalogs", "--root", str(root / "shelves")]),
                0,
            )
            self.assertEqual(receipt_main(["status", "-c", str(catalog)]), 0)
            self.assertEqual(receipt_main(["list", "-c", str(catalog), "-q", "beta"]), 0)
            self.assertEqual(receipt_main(["find", "echo", "-c", str(catalog)]), 0)
            self.assertEqual(receipt_main(["show", "beta.py", "-c", str(catalog)]), 0)
            self.assertEqual(receipt_main(["find", "NopeSymbol", "-c", str(catalog)]), 1)

    def test_show_ambiguous_basename(self):
        fixtures = ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog"
            # two files same basename in nested dirs
            tree = Path(tmp) / "tree"
            (tree / "a").mkdir(parents=True)
            (tree / "b").mkdir(parents=True)
            (tree / "a" / "dup.py").write_text("def one():\n    return 1\n", encoding="utf-8")
            (tree / "b" / "dup.py").write_text("def two():\n    return 2\n", encoding="utf-8")
            collect_to(tree, catalog)
            with self.assertRaises(ShelfError):
                show_receipt(catalog, "dup.py")
            shown = show_receipt(catalog, "a/dup.py")
            self.assertEqual(shown["rel"], "a/dup.py")


if __name__ == "__main__":
    unittest.main()
