import enum
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Customer, Order, OrderStatus
from app.schemas import (
    AovByCityResponse,
    AovCityRow,
    RepeatPurchaseResponse,
    RevenueBucket,
    RevenueResponse,
    RevenueTotals,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])


class Granularity(str, enum.Enum):
    day = "day"
    week = "week"
    month = "month"


def _as_date(value: object) -> date:
    # func.date() returns a date on Postgres but an ISO string on SQLite.
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _bucket_start_and_label(d: date, granularity: Granularity) -> tuple[date, str]:
    if granularity is Granularity.day:
        return d, d.isoformat()
    if granularity is Granularity.week:
        start = d - timedelta(days=d.weekday())  # Monday of the ISO week
        iso = d.isocalendar()
        return start, f"{iso.year}-W{iso.week:02d}"
    return d.replace(day=1), d.strftime("%Y-%m")


@router.get("/revenue", response_model=RevenueResponse)
def revenue(
    granularity: Granularity = Granularity.day,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    session: Session = Depends(get_session),
):
    """Revenue over time (UTC dates). Cancelled orders are excluded entirely;
    refunded orders carry negative totals and reduce net revenue."""
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "`from` must be on or before `to`.")

    day = func.date(Order.order_date).label("day")
    stmt = (
        select(
            day,
            func.sum(
                case((Order.status == OrderStatus.completed, 1), else_=0)
            ).label("order_count"),
            func.sum(
                case((Order.status == OrderStatus.refunded, 1), else_=0)
            ).label("refund_count"),
            func.sum(
                case(
                    (Order.status == OrderStatus.completed, Order.total_amount),
                    else_=0,
                )
            ).label("gross"),
            func.sum(
                case(
                    (Order.status == OrderStatus.refunded, Order.total_amount),
                    else_=0,
                )
            ).label("refunds"),
        )
        .where(Order.status != OrderStatus.cancelled)
        .group_by(day)
        .order_by(day)
    )
    if from_date:
        stmt = stmt.where(day >= from_date.isoformat())
    if to_date:
        stmt = stmt.where(day <= to_date.isoformat())

    buckets: dict[date, dict] = {}
    for row in session.execute(stmt):
        d = _as_date(row.day)
        start, label = _bucket_start_and_label(d, granularity)
        b = buckets.setdefault(
            start,
            {
                "label": label,
                "order_count": 0,
                "refund_count": 0,
                "gross": 0.0,
                "refunds": 0.0,
            },
        )
        b["order_count"] += int(row.order_count or 0)
        b["refund_count"] += int(row.refund_count or 0)
        b["gross"] += float(row.gross or 0)
        b["refunds"] += float(row.refunds or 0)

    out = [
        RevenueBucket(
            period_start=start,
            label=b["label"],
            order_count=b["order_count"],
            refund_count=b["refund_count"],
            gross_revenue=round(b["gross"], 2),
            refund_total=round(b["refunds"], 2),
            net_revenue=round(b["gross"] + b["refunds"], 2),
        )
        for start, b in sorted(buckets.items())
    ]

    total_orders = sum(b.order_count for b in out)
    total_gross = round(sum(b.gross_revenue for b in out), 2)
    total_refunds = round(sum(b.refund_total for b in out), 2)
    totals = RevenueTotals(
        order_count=total_orders,
        refund_count=sum(b.refund_count for b in out),
        gross_revenue=total_gross,
        refund_total=total_refunds,
        net_revenue=round(total_gross + total_refunds, 2),
        avg_order_value=round(total_gross / total_orders, 2) if total_orders else 0.0,
    )
    return RevenueResponse(
        granularity=granularity.value,
        from_date=from_date,
        to_date=to_date,
        buckets=out,
        totals=totals,
    )


@router.get("/repeat-purchase-rate", response_model=RepeatPurchaseResponse)
def repeat_purchase_rate(session: Session = Depends(get_session)):
    """Share of purchasing customers who placed 2+ orders. A "purchase" is any
    non-cancelled order (refunded orders were still purchases)."""
    per_customer = (
        select(Order.customer_id, func.count().label("n"))
        .where(Order.status != OrderStatus.cancelled)
        .group_by(Order.customer_id)
        .subquery()
    )
    total, repeat = session.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(case((per_customer.c.n >= 2, 1), else_=0)), 0
            ),
        ).select_from(per_customer)
    ).one()
    return RepeatPurchaseResponse(
        customers_with_purchases=int(total),
        repeat_customers=int(repeat),
        repeat_purchase_rate=round(repeat / total, 4) if total else 0.0,
    )


@router.get("/aov-by-city", response_model=AovByCityResponse)
def aov_by_city(session: Session = Depends(get_session)):
    """Average completed-order value per customer city. Orders whose customer
    is a placeholder (unknown in customers.csv) are grouped under "Unknown"."""
    city = func.coalesce(Customer.city, "Unknown").label("city")
    rows = session.execute(
        select(
            city,
            func.count().label("order_count"),
            func.sum(Order.total_amount).label("revenue"),
            func.avg(Order.total_amount).label("aov"),
        )
        .join(Customer, Order.customer_id == Customer.customer_id)
        .where(Order.status == OrderStatus.completed)
        .group_by(city)
        .order_by(func.avg(Order.total_amount).desc())
    ).all()
    return AovByCityResponse(
        items=[
            AovCityRow(
                city=row.city,
                order_count=int(row.order_count),
                revenue=round(float(row.revenue), 2),
                avg_order_value=round(float(row.aov), 2),
            )
            for row in rows
        ]
    )
