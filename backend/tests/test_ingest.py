from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.ingest.pipeline import run_ingest
from app.models import Customer, DataQualityIssue, Order, OrderItem


def _issues_of(session, issue_type: str, run_id: int):
    return (
        session.execute(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type == issue_type,
                DataQualityIssue.run_id == run_id,
            )
        )
        .scalars()
        .all()
    )


def test_duplicate_order_ids_collapse_to_one_row(ingested):
    with SessionLocal() as s:
        for oid in ("ORD-5", "ORD-6"):
            rows = s.execute(select(Order).where(Order.order_id == oid)).scalars().all()
            assert len(rows) == 1
        assert len(_issues_of(s, "duplicate_exact", ingested["run_id"])) == 1
        assert len(_issues_of(s, "duplicate_conflicting", ingested["run_id"])) == 1


def test_conflicting_duplicate_keeps_latest_event(ingested):
    with SessionLocal() as s:
        order = s.get(Order, "ORD-6")
        got = order.order_date
        if got.tzinfo is None:  # SQLite may round-trip naive; values are UTC
            got = got.replace(tzinfo=timezone.utc)
        assert got == datetime(2026, 2, 2, 8, 30, tzinfo=timezone.utc)


def test_unknown_customer_gets_flagged_placeholder(ingested):
    with SessionLocal() as s:
        ghost = s.get(Customer, "CUST-9999")
        assert ghost is not None
        assert ghost.is_placeholder is True
        assert ghost.name is None
        assert len(_issues_of(s, "unknown_customer", ingested["run_id"])) == 1
        # The order itself must not be lost.
        assert s.get(Order, "ORD-7") is not None


def test_refund_negative_total_is_valid_not_mismatch(ingested):
    with SessionLocal() as s:
        refund = s.get(Order, "ORD-3")
        assert float(refund.total_amount) == -300.0
        mismatches = _issues_of(s, "total_mismatch", ingested["run_id"])
        assert [m.record_id for m in mismatches] == ["ORD-8"]  # only the real one


def test_missing_email_stored_null_and_flagged(ingested):
    with SessionLocal() as s:
        cust = s.get(Customer, "CUST-0002")
        assert cust.email is None
        flagged = _issues_of(s, "missing_email", ingested["run_id"])
        assert [f.record_id for f in flagged] == ["CUST-0002"]


def test_all_three_date_formats_parsed(ingested):
    formats = ingested["order_date_formats_seen"]
    assert formats["iso8601"] >= 1
    assert formats["dmy"] >= 1
    assert formats["epoch"] >= 1


def test_ingest_is_idempotent(ingested, data_files):
    orders_path, customers_path = data_files
    with SessionLocal() as s:
        second = run_ingest(s, orders_path, customers_path)
    with SessionLocal() as s:
        assert len(s.execute(select(Order)).scalars().all()) == 8
        assert len(s.execute(select(Customer)).scalars().all()) == 4  # 3 real + 1 placeholder
        # Line items replaced, not appended.
        items = s.execute(select(OrderItem)).scalars().all()
        assert len(items) == 9
    assert second["orders"]["unique_orders_ingested"] == 8


def test_summary_counts(ingested):
    assert ingested["orders"]["records_in_file"] == 10
    assert ingested["orders"]["duplicate_records_discarded"] == 2
    assert ingested["orders"]["unique_orders_ingested"] == 8
    assert ingested["customers"]["ingested"] == 3
    assert ingested["issues_by_type"]["unknown_customer"] == 1
