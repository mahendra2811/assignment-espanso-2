"""CLI entry point: python -m app.ingest [--orders PATH] [--customers PATH]"""
import argparse
import json
from pathlib import Path

from app import models  # noqa: F401  (register tables with Base.metadata)
from app.config import DATA_DIR
from app.database import Base, SessionLocal, engine
from app.ingest.pipeline import run_ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the e-commerce feed files.")
    parser.add_argument("--orders", default=DATA_DIR / "orders.json", type=Path)
    parser.add_argument("--customers", default=DATA_DIR / "customers.csv", type=Path)
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        summary = run_ingest(session, args.orders, args.customers)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
