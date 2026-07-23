from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Customer, Order, OrderStatus
from app.schemas import TopCustomer, TopCustomersResponse

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/top", response_model=TopCustomersResponse)
def top_customers(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Customers ranked by net spend (completed minus refunded; cancelled
    orders excluded). Placeholder customers — referenced by orders but missing
    from customers.csv — are included and flagged."""
    net_spend = func.sum(Order.total_amount).label("net_spend")
    rows = session.execute(
        select(
            Customer.customer_id,
            Customer.name,
            Customer.city,
            Customer.email,
            Customer.is_placeholder,
            func.count().label("order_count"),
            net_spend,
        )
        .join(Order, Order.customer_id == Customer.customer_id)
        .where(Order.status != OrderStatus.cancelled)
        .group_by(
            Customer.customer_id,
            Customer.name,
            Customer.city,
            Customer.email,
            Customer.is_placeholder,
        )
        .order_by(net_spend.desc(), Customer.customer_id)
        .limit(limit)
        .offset(offset)
    ).all()

    total = session.execute(
        select(func.count(func.distinct(Order.customer_id))).where(
            Order.status != OrderStatus.cancelled
        )
    ).scalar_one()

    return TopCustomersResponse(
        items=[
            TopCustomer(
                customer_id=row.customer_id,
                name=row.name,
                city=row.city,
                email=row.email,
                is_placeholder=row.is_placeholder,
                order_count=int(row.order_count),
                net_spend=round(float(row.net_spend), 2),
            )
            for row in rows
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )
