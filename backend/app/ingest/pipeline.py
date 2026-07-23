"""Ingest pipeline for the third-party feed (orders.json + customers.csv).

Design principles:
  * Never trust the feed — every record passes explicit validation.
  * Never fix silently — every coercion/discard is written to
    data_quality_issues, tied to an ingest_runs row, and surfaced via the API.
  * Idempotent — re-running the ingest upserts, so a re-delivered feed
    (which this one simulates: 28 duplicated order_ids) is safe.
"""
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.ingest.parsers import parse_order_date
from app.models import (
    Customer,
    DataQualityIssue,
    IngestRun,
    Order,
    OrderItem,
    OrderStatus,
)

VALID_STATUSES = {s.value for s in OrderStatus}


class RawItem(BaseModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    qty: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class RawOrder(BaseModel):
    order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    order_date: int | float | str
    items: list[RawItem] = Field(min_length=1)
    total_amount: Decimal
    currency: str = Field(min_length=1)
    status: str = Field(min_length=1)


class RawCustomer(BaseModel):
    customer_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    signup_date: date
    email: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def blank_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v


@dataclass
class _ParsedOrder:
    idx: int  # position in the feed file, used as a deterministic tie-breaker
    raw: dict
    model: RawOrder
    order_dt: datetime
    date_format: str


def run_ingest(session: Session, orders_path: Path, customers_path: Path) -> dict:
    """Ingest both files into the DB. Returns a JSON-able summary dict."""
    issues: list[dict] = []

    def flag(source: str, record_id: str, issue_type: str, detail: str) -> None:
        issues.append(
            {
                "source": source,
                "record_id": record_id,
                "issue_type": issue_type,
                "detail": detail,
            }
        )

    # ---------------------------------------------------------------- customers
    with open(customers_path, newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))

    known_customer_ids: set[str] = set()
    customers_ingested = 0
    for i, row in enumerate(csv_rows):
        cleaned = {
            k: (v.strip() if isinstance(v, str) else v)
            for k, v in row.items()
            if k is not None
        }
        try:
            c = RawCustomer(**cleaned)
        except ValidationError as exc:
            flag(
                "customers.csv",
                cleaned.get("customer_id") or f"row {i + 2}",
                "invalid_record",
                f"row failed validation and was skipped: {exc.errors()[0]['msg']}",
            )
            continue
        if c.email is None:
            flag(
                "customers.csv",
                c.customer_id,
                "missing_email",
                "email column is blank; stored as NULL",
            )
        elif "@" not in c.email:
            flag(
                "customers.csv",
                c.customer_id,
                "invalid_email",
                f"email {c.email!r} does not look like an address; stored as-is",
            )
        session.merge(
            Customer(
                customer_id=c.customer_id,
                name=c.name,
                city=c.city,
                signup_date=c.signup_date,
                email=c.email,
                is_placeholder=False,
            )
        )
        known_customer_ids.add(c.customer_id)
        customers_ingested += 1

    # ------------------------------------------------------- orders: validation
    raw_records = json.loads(Path(orders_path).read_text(encoding="utf-8"))
    if not isinstance(raw_records, list):
        raise ValueError("orders.json must contain a JSON array of order records")

    date_formats: Counter = Counter()
    parsed: list[_ParsedOrder] = []
    skipped_invalid = 0
    for idx, rec in enumerate(raw_records):
        rec_id = (
            str(rec.get("order_id", f"index {idx}"))
            if isinstance(rec, dict)
            else f"index {idx}"
        )
        try:
            model = RawOrder(**rec) if isinstance(rec, dict) else None
        except ValidationError as exc:
            model = None
            reason = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                for e in exc.errors()[:3]
            )
            flag("orders.json", rec_id, "invalid_record", f"skipped: {reason}")
        if model is None:
            if not isinstance(rec, dict):
                flag("orders.json", rec_id, "invalid_record", "record is not an object")
            skipped_invalid += 1
            continue
        if model.status not in VALID_STATUSES:
            flag(
                "orders.json",
                rec_id,
                "invalid_status",
                f"unknown status {model.status!r}; record skipped",
            )
            skipped_invalid += 1
            continue
        try:
            order_dt, fmt = parse_order_date(model.order_date)
        except ValueError as exc:
            flag("orders.json", rec_id, "unparseable_date", f"skipped: {exc}")
            skipped_invalid += 1
            continue
        date_formats[fmt] += 1
        parsed.append(_ParsedOrder(idx, rec, model, order_dt, fmt))

    # ---------------------------------------------------- orders: deduplication
    # The feed re-delivers events: some order_ids appear twice, either as exact
    # copies or with the order_date shifted by minutes. Rule: keep the record
    # with the latest order_date (latest event wins), feed position as tie-break.
    groups: dict[str, list[_ParsedOrder]] = defaultdict(list)
    for p in parsed:
        groups[p.model.order_id].append(p)

    canonical: list[_ParsedOrder] = []
    duplicates_discarded = 0
    for order_id, group in groups.items():
        group_sorted = sorted(group, key=lambda p: (p.order_dt, p.idx))
        keep = group_sorted[-1]
        canonical.append(keep)
        for other in group_sorted[:-1]:
            duplicates_discarded += 1
            if other.raw == keep.raw:
                flag(
                    "orders.json",
                    order_id,
                    "duplicate_exact",
                    "identical record repeated in feed; kept a single copy",
                )
            else:
                differing = sorted(
                    k
                    for k in set(keep.raw) | set(other.raw)
                    if keep.raw.get(k) != other.raw.get(k)
                )
                flag(
                    "orders.json",
                    order_id,
                    "duplicate_conflicting",
                    f"feed contains conflicting copies (fields differ: {', '.join(differing)}); "
                    "kept the copy with the latest order_date",
                )

    # ------------------------------------------- orders: integrity + persistence
    placeholders_created: set[str] = set()
    orders_ingested = 0
    for p in sorted(canonical, key=lambda p: p.model.order_id):
        m = p.model
        if m.customer_id not in known_customer_ids:
            if m.customer_id not in placeholders_created:
                session.merge(Customer(customer_id=m.customer_id, is_placeholder=True))
                placeholders_created.add(m.customer_id)
            flag(
                "orders.json",
                m.order_id,
                "unknown_customer",
                f"customer_id {m.customer_id!r} not in customers.csv; "
                "created a flagged placeholder customer so the order is not lost",
            )

        # Refunded orders state a negative total (reversal of the charge), so
        # the stated total must equal -(sum of line items) for refunds and
        # +(sum of line items) otherwise. Anything else is flagged.
        items_total = sum(i.qty * i.unit_price for i in m.items)
        expected_total = -items_total if m.status == OrderStatus.refunded.value else items_total
        if m.total_amount != expected_total:
            flag(
                "orders.json",
                m.order_id,
                "total_mismatch",
                f"stated total {m.total_amount} != expected {expected_total} "
                f"(line items sum {items_total}, status {m.status}); stored the stated value",
            )
        if m.currency != "INR":
            flag(
                "orders.json",
                m.order_id,
                "unexpected_currency",
                f"currency {m.currency!r} (feed is assumed INR); stored as-is",
            )

        session.merge(
            Order(
                order_id=m.order_id,
                customer_id=m.customer_id,
                order_date=p.order_dt,
                status=OrderStatus(m.status),
                total_amount=m.total_amount,
                currency=m.currency,
            )
        )
        # Replace line items wholesale — simplest correct upsert for a feed.
        session.execute(delete(OrderItem).where(OrderItem.order_id == m.order_id))
        for pos, item in enumerate(m.items):
            session.add(
                OrderItem(
                    order_id=m.order_id,
                    position=pos,
                    sku=item.sku,
                    name=item.name,
                    qty=item.qty,
                    unit_price=item.unit_price,
                )
            )
        orders_ingested += 1

    # ------------------------------------------------------------ run + issues
    summary = {
        "customers": {
            "rows_in_file": len(csv_rows),
            "ingested": customers_ingested,
            "placeholders_created_for_unknown_ids": len(placeholders_created),
        },
        "orders": {
            "records_in_file": len(raw_records),
            "skipped_invalid": skipped_invalid,
            "duplicate_records_discarded": duplicates_discarded,
            "unique_orders_ingested": orders_ingested,
        },
        "order_date_formats_seen": dict(date_formats),
        "issues_by_type": dict(Counter(i["issue_type"] for i in issues)),
        "total_issues": len(issues),
    }

    run = IngestRun(ran_at=datetime.now(timezone.utc), summary=summary)
    session.add(run)
    session.flush()
    for issue in issues:
        session.add(DataQualityIssue(run_id=run.id, **issue))
    session.commit()

    return {"run_id": run.id, **summary}
