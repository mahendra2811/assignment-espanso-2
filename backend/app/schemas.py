"""Pydantic response models for the API.

Monetary values are serialised as floats (rounded to 2dp) for JSON ergonomics;
the database keeps exact NUMERIC values.
"""
from datetime import date, datetime

from pydantic import BaseModel


class RevenueBucket(BaseModel):
    period_start: date
    label: str
    order_count: int
    refund_count: int
    gross_revenue: float
    refund_total: float
    net_revenue: float


class RevenueTotals(BaseModel):
    order_count: int
    refund_count: int
    gross_revenue: float
    refund_total: float
    net_revenue: float
    avg_order_value: float


class RevenueResponse(BaseModel):
    granularity: str
    from_date: date | None
    to_date: date | None
    buckets: list[RevenueBucket]
    totals: RevenueTotals


class TopCustomer(BaseModel):
    customer_id: str
    name: str | None
    city: str | None
    email: str | None
    is_placeholder: bool
    order_count: int
    net_spend: float


class TopCustomersResponse(BaseModel):
    items: list[TopCustomer]
    total: int
    limit: int
    offset: int


class RepeatPurchaseResponse(BaseModel):
    customers_with_purchases: int
    repeat_customers: int
    repeat_purchase_rate: float


class AovCityRow(BaseModel):
    city: str
    order_count: int
    revenue: float
    avg_order_value: float


class AovByCityResponse(BaseModel):
    items: list[AovCityRow]


class OrderListItem(BaseModel):
    order_id: str
    customer_id: str
    order_date: datetime
    status: str
    currency: str
    total_amount: float
    item_count: int


class OrdersResponse(BaseModel):
    items: list[OrderListItem]
    total: int
    limit: int
    offset: int


class OrderItemOut(BaseModel):
    sku: str
    name: str
    qty: int
    unit_price: float
    line_total: float


class OrderDetail(BaseModel):
    order_id: str
    customer_id: str
    customer_name: str | None
    order_date: datetime
    status: str
    currency: str
    total_amount: float
    items_total: float
    items: list[OrderItemOut]


class IssueOut(BaseModel):
    source: str
    record_id: str
    issue_type: str
    detail: str | None


class DataQualityResponse(BaseModel):
    ingested: bool
    run_id: int | None = None
    ran_at: datetime | None = None
    summary: dict | None = None
    issue_counts: dict[str, int] = {}
    issues: list[IssueOut] = []
