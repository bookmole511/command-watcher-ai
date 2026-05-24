"""Minimal database connectivity harness.

This checks that configured DB credentials can establish a connection without
printing secrets.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from src.config import DB_HOST, DB_NAME, DB_PORT, DB_URL, DB_USER


def main() -> int:
    print(f"db smoke: {DB_HOST}:{DB_PORT}/{DB_NAME} user={DB_USER}")

    try:
        engine = create_engine(DB_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            value = conn.execute(text("SELECT 1")).scalar()
    except Exception as exc:
        print(f"FAIL db connection: {exc}")
        return 1

    if value != 1:
        print(f"FAIL unexpected SELECT 1 result: {value}")
        return 1

    print("PASS db connection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
