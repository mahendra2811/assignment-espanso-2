"""Test setup: an in-memory SQLite DB shared by the app and the fixtures.

DATABASE_URL must be set before any app module is imported, which is why it
happens at the top of this file. The app's engine uses a StaticPool for
in-memory SQLite, so every session sees the same database.
"""
import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import models  # noqa: F401
from app.database import Base, SessionLocal, engine
from app.ingest.pipeline import run_ingest
from app.main import app

# ---------------------------------------------------------------------------
# Fixture dataset: small but contains every trap present in the real feed.
# ---------------------------------------------------------------------------

CUSTOMERS_CSV = """customer_id,name,city,signup_date,email
CUST-0001,Asha Rao,Pune,2025-01-05,asha@example.com
CUST-0002,Vik Shah,Delhi,2025-02-01,
CUST-0003,Meera Iyer,Pune,2025-03-01,meera@example.com
"""

ORDERS = [
    # Plain completed order, ISO date.
    {
        "order_id": "ORD-1",
        "customer_id": "CUST-0001",
        "order_date": "2026-01-10T10:00:00Z",
        "items": [
            {"sku": "S1", "name": "Serum", "qty": 2, "unit_price": 100},
            {"sku": "S2", "name": "Balm", "qty": 1, "unit_price": 50},
        ],
        "total_amount": 250,
        "currency": "INR",
        "status": "completed",
    },
    # DD/MM/YYYY date with day > 12 (proves day-first parsing).
    {
        "order_id": "ORD-2",
        "customer_id": "CUST-0001",
        "order_date": "15/01/2026",
        "items": [{"sku": "S1", "name": "Serum", "qty": 1, "unit_price": 120}],
        "total_amount": 120,
        "currency": "INR",
        "status": "completed",
    },
    # Epoch-seconds date, refunded → stated total is negative (valid).
    {
        "order_id": "ORD-3",
        "customer_id": "CUST-0002",
        "order_date": "1768191660",  # 2026-01-12T04:21:00Z
        "items": [{"sku": "S3", "name": "Mask", "qty": 3, "unit_price": 100}],
        "total_amount": -300,
        "currency": "INR",
        "status": "refunded",
    },
    # Cancelled order — must be excluded from revenue metrics.
    {
        "order_id": "ORD-4",
        "customer_id": "CUST-0003",
        "order_date": "2026-01-20T09:00:00Z",
        "items": [{"sku": "S4", "name": "Shampoo", "qty": 1, "unit_price": 500}],
        "total_amount": 500,
        "currency": "INR",
        "status": "cancelled",
    },
    # Exact duplicate pair (same payload twice).
    {
        "order_id": "ORD-5",
        "customer_id": "CUST-0003",
        "order_date": "2026-02-01T08:00:00Z",
        "items": [{"sku": "S1", "name": "Serum", "qty": 1, "unit_price": 150}],
        "total_amount": 150,
        "currency": "INR",
        "status": "completed",
    },
    {
        "order_id": "ORD-5",
        "customer_id": "CUST-0003",
        "order_date": "2026-02-01T08:00:00Z",
        "items": [{"sku": "S1", "name": "Serum", "qty": 1, "unit_price": 150}],
        "total_amount": 150,
        "currency": "INR",
        "status": "completed",
    },
    # Conflicting duplicate pair (order_date differs; later one must win).
    {
        "order_id": "ORD-6",
        "customer_id": "CUST-0003",
        "order_date": "2026-02-02T08:00:00Z",
        "items": [{"sku": "S2", "name": "Balm", "qty": 2, "unit_price": 100}],
        "total_amount": 200,
        "currency": "INR",
        "status": "completed",
    },
    {
        "order_id": "ORD-6",
        "customer_id": "CUST-0003",
        "order_date": "2026-02-02T08:30:00Z",
        "items": [{"sku": "S2", "name": "Balm", "qty": 2, "unit_price": 100}],
        "total_amount": 200,
        "currency": "INR",
        "status": "completed",
    },
    # Order referencing a customer missing from customers.csv.
    {
        "order_id": "ORD-7",
        "customer_id": "CUST-9999",
        "order_date": "2026-02-05T12:00:00Z",
        "items": [{"sku": "S5", "name": "Oil", "qty": 1, "unit_price": 100}],
        "total_amount": 100,
        "currency": "INR",
        "status": "completed",
    },
    # Stated total that genuinely disagrees with the line items.
    {
        "order_id": "ORD-8",
        "customer_id": "CUST-0002",
        "order_date": "2026-02-06T12:00:00Z",
        "items": [{"sku": "S6", "name": "Toner", "qty": 1, "unit_price": 100}],
        "total_amount": 90,
        "currency": "INR",
        "status": "completed",
    },
]


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def data_files(tmp_path: Path) -> tuple[Path, Path]:
    orders_path = tmp_path / "orders.json"
    customers_path = tmp_path / "customers.csv"
    orders_path.write_text(json.dumps(ORDERS))
    customers_path.write_text(CUSTOMERS_CSV)
    return orders_path, customers_path


@pytest.fixture()
def ingested(db, data_files) -> dict:
    orders_path, customers_path = data_files
    with SessionLocal() as session:
        return run_ingest(session, orders_path, customers_path)


@pytest.fixture()
def client(ingested):
    with TestClient(app) as c:
        yield c
