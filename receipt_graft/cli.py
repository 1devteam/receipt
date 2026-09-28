from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.io import ReceiptIOError
from receipt_graft.graph import ReceiptGraftError
from receipt_graft.integration import reconstruct_catalog


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="receipt-graft",
        description="Reconstruct Receipt's internal G.R.A.F.T.+ stock graph",
    )
    p.add_argument("catalog", help="catalog directory or receipts.json")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = reconstruct_catalog(Path(args.catalog))
    except (OSError, ValueError, ReceiptIOError, ReceiptGraftError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0
