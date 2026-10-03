from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.io import read_json
from receipt_stock.bootstrap import bootstrap_stock
from receipt_stock.manifest import StockManifestError, load_bootstrap_manifest


def _print(data) -> None:
    print(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="receipt-stock",
        description="Receipt curated stock bootstrap and inventory",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_manifest = sub.add_parser("manifest", help="show the validated bootstrap manifest")
    p_manifest.add_argument("--manifest", default=None)

    p_bootstrap = sub.add_parser("bootstrap", help="materialize pinned curated stock catalogs")
    p_bootstrap.add_argument("-o", "--out", required=True, help="stock root directory")
    p_bootstrap.add_argument("--manifest", default=None, help="override bootstrap manifest")
    p_bootstrap.add_argument("--force", action="store_true", help="replace existing source catalogs")

    p_status = sub.add_parser("status", help="show a materialized stock inventory")
    p_status.add_argument("root", help="stock root containing stock-index.v1.json")

    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.cmd == "manifest":
            _print(load_bootstrap_manifest(args.manifest))
            return 0
        if args.cmd == "bootstrap":
            result = bootstrap_stock(
                Path(args.out),
                manifest_path=Path(args.manifest) if args.manifest else None,
                force=args.force,
            )
            _print(result)
            return 0 if result.get("totals", {}).get("files") else 2
        if args.cmd == "status":
            root = Path(args.root).expanduser().resolve()
            index = read_json(root / "stock-index.v1.json")
            _print(index)
            return 0
    except (StockManifestError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1
