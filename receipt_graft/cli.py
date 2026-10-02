from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.io import ReceiptIOError
from receipt_graft.graph import ReceiptGraftError
from receipt_graft.impact import ReceiptGraftImpactError
from receipt_graft.integration import analyze_catalog_impact, reconstruct_catalog


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="receipt-graft",
        description="Reconstruct Receipt's internal G.R.A.F.T.+ stock graph",
    )
    p.add_argument("catalog", help="catalog directory or receipts.json")
    p.add_argument(
        "--impact",
        nargs="+",
        metavar="SEED",
        help="derive blast radius/proof slice for one or more rel/module/symbol seeds",
    )
    p.add_argument(
        "--impact-out",
        help="optional impact report path (default: catalog graft/impact.v1.json)",
    )
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.impact:
            result = analyze_catalog_impact(
                Path(args.catalog),
                args.impact,
                out=Path(args.impact_out) if args.impact_out else None,
            )
        else:
            result = reconstruct_catalog(Path(args.catalog))
    except (
        OSError,
        ValueError,
        ReceiptIOError,
        ReceiptGraftError,
        ReceiptGraftImpactError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0
