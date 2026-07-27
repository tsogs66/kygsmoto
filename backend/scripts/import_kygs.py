#!/usr/bin/env python3
"""CLI: import KYGS APRIL 2025.xlsm into the local database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.database import Base, SessionLocal, engine
from app.services.kygs_import import import_kygs_workbook


def main() -> int:
    parser = argparse.ArgumentParser(description="Import KYGS Excel workbook")
    parser.add_argument(
        "workbook",
        nargs="?",
        default=str(ROOT.parent / "KYGS APRIL 2025.xlsm"),
        help="Path to .xlsm workbook",
    )
    parser.add_argument("--keep-existing", action="store_true", help="Do not wipe current data")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = import_kygs_workbook(
            db,
            args.workbook,
            replace_existing=not args.keep_existing,
        )
    finally:
        db.close()

    print(result["message"])
    print(
        f"products={result['products_created']} services={result['services_created']} "
        f"delisted={result['delisted_count']} sales={result['sales_created']} "
        f"lines={result['sale_lines']} unmatched={result['unmatched_skus']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
