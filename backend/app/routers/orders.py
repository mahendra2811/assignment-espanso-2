from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_session
from app.models import Order, OrderStatus
from app.schemas import OrderDetail, OrderItemOut, OrderListItem, OrdersResponse

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=OrdersResponse)
def list_orders(
    status: OrderStatus | None = None,
    customer_id: str | None = None,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "`from` must be on or before `to`.")

    stmt = select(Order).options(selectinload(Order.items))
    count_stmt = select(func.count()).select_from(Order)

    def apply_filters(s):
        if status is not None:
            s = s.where(Order.status == status)
        if customer_id is not None:
            s = s.where(Order.customer_id == customer_id)
        if from_date is not None:
            s = s.where(
                Order.order_date
                >= datetime.combine(from_date, time.min, tzinfo=timezone.utc)
            )
        if to_date is not None:
            s = s.where(
                Order.order_date
                <= datetime.combine(to_date, time.max, tzinfo=timezone.utc)
            )
        return s

    total = session.execute(apply_filters(count_stmt)).scalar_one()
    orders = (
        session.execute(
            apply_filters(stmt)
            .order_by(Order.order_date.desc(), Order.order_id)
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return OrdersResponse(
        items=[
            OrderListItem(
                order_id=o.order_id,
                customer_id=o.customer_id,
                order_date=o.order_date,
                status=o.status.value,
                currency=o.currency,
                total_amount=float(o.total_amount),
                item_count=len(o.items),
            )
            for o in orders
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(order_id: str, session: Session = Depends(get_session)):
    order = session.get(
        Order, order_id, options=[selectinload(Order.items), selectinload(Order.customer)]
    )
    if order is None:
        raise HTTPException(404, f"Order {order_id!r} not found.")
    items_total = sum(i.qty * i.unit_price for i in order.items)
    return OrderDetail(
        order_id=order.order_id,
        customer_id=order.customer_id,
        customer_name=order.customer.name if order.customer else None,
        order_date=order.order_date,
        status=order.status.value,
        currency=order.currency,
        total_amount=float(order.total_amount),
        items_total=float(items_total),
        items=[
            OrderItemOut(
                sku=i.sku,
                name=i.name,
                qty=i.qty,
                unit_price=float(i.unit_price),
                line_total=float(i.qty * i.unit_price),
            )
            for i in order.items
        ],
    )
