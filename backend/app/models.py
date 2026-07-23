import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OrderStatus(str, enum.Enum):
    completed = "completed"
    cancelled = "cancelled"
    refunded = "refunded"


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    # Nullable because orders can reference customers missing from the CSV;
    # we create a flagged placeholder row for them (see ingest pipeline).
    name: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(80), index=True)
    signup_date: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(254))
    is_placeholder: Mapped[bool] = mapped_column(default=False)

    orders = relationship("Order", back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.customer_id"), index=True
    )
    # Normalised to UTC at ingest, whatever format the feed used.
    order_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(
            OrderStatus,
            name="order_status",
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        index=True,
    )
    # Stated feed total, stored as-is. Refunded orders carry a negative total
    # (feed semantics: the stated total reverses the original charge).
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")

    customer = relationship("Customer", back_populates="orders")
    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.position",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order = relationship("Order", back_populates="items")


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSON)

    issues = relationship("DataQualityIssue", back_populates="run")


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ingest_runs.id"), index=True)
    source: Mapped[str] = mapped_column(String(30))
    record_id: Mapped[str] = mapped_column(String(40), index=True)
    issue_type: Mapped[str] = mapped_column(String(40), index=True)
    detail: Mapped[str | None] = mapped_column(Text)

    run = relationship("IngestRun", back_populates="issues")
