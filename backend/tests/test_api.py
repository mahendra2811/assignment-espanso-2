"""Endpoint behaviour against the ingested fixture dataset.

Fixture ground truth (see conftest.py):
  completed orders: ORD-1 250 (Pune), ORD-2 120 (Pune), ORD-5 150 (Pune),
                    ORD-6 200 (Pune), ORD-7 100 (Unknown), ORD-8 90 (Delhi)
  refunded:  ORD-3 -300 (Delhi)   cancelled: ORD-4 500 (Pune, excluded)
"""


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_revenue_excludes_cancelled_and_nets_refunds(client):
    body = client.get("/api/metrics/revenue?granularity=day").json()
    totals = body["totals"]
    assert totals["order_count"] == 6
    assert totals["gross_revenue"] == 910.0  # 250+120+150+200+100+90 — no ORD-4
    assert totals["refund_total"] == -300.0
    assert totals["net_revenue"] == 610.0
    # Cancelled order's date must not create a bucket by itself.
    assert all(b["order_count"] + b["refund_count"] > 0 for b in body["buckets"])


def test_revenue_week_granularity_buckets(client):
    body = client.get("/api/metrics/revenue?granularity=week").json()
    labels = [b["label"] for b in body["buckets"]]
    assert all("W" in label for label in labels)
    # Weekly totals must equal daily totals.
    daily = client.get("/api/metrics/revenue?granularity=day").json()
    assert sum(b["net_revenue"] for b in body["buckets"]) == sum(
        b["net_revenue"] for b in daily["buckets"]
    )


def test_revenue_date_filter(client):
    body = client.get("/api/metrics/revenue?from=2026-02-01&to=2026-02-28").json()
    assert body["totals"]["order_count"] == 4  # ORD-5, ORD-6, ORD-7, ORD-8
    assert body["totals"]["refund_count"] == 0


def test_revenue_invalid_range_is_400_with_error_envelope(client):
    resp = client.get("/api/metrics/revenue?from=2026-03-01&to=2026-01-01")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_revenue_bad_granularity_is_422(client):
    resp = client.get("/api/metrics/revenue?granularity=fortnight")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_top_customers_ranking_and_pagination(client):
    body = client.get("/api/customers/top?limit=2").json()
    assert body["total"] == 4
    ids = [c["customer_id"] for c in body["items"]]
    # CUST-0001: 370, CUST-0003: 350, CUST-9999: 100, CUST-0002: -210 (refund)
    assert ids == ["CUST-0001", "CUST-0003"]
    assert body["items"][0]["net_spend"] == 370.0

    page2 = client.get("/api/customers/top?limit=2&offset=2").json()
    ids2 = [c["customer_id"] for c in page2["items"]]
    assert ids2 == ["CUST-9999", "CUST-0002"]
    placeholder = page2["items"][0]
    assert placeholder["is_placeholder"] is True
    assert page2["items"][1]["net_spend"] == -210.0


def test_repeat_purchase_rate(client):
    body = client.get("/api/metrics/repeat-purchase-rate").json()
    # Purchasers: 0001 (2 orders), 0002 (2), 0003 (2), 9999 (1) → 3/4 repeat.
    assert body["customers_with_purchases"] == 4
    assert body["repeat_customers"] == 3
    assert body["repeat_purchase_rate"] == 0.75


def test_aov_by_city_groups_placeholder_as_unknown(client):
    body = client.get("/api/metrics/aov-by-city").json()
    by_city = {row["city"]: row for row in body["items"]}
    assert by_city["Pune"]["order_count"] == 4
    assert by_city["Pune"]["avg_order_value"] == 180.0  # (250+120+150+200)/4
    assert by_city["Unknown"]["order_count"] == 1
    assert by_city["Delhi"]["order_count"] == 1  # refund excluded from AOV
    assert by_city["Delhi"]["revenue"] == 90.0


def test_orders_list_filters_and_pagination(client):
    body = client.get("/api/orders?status=completed&limit=3").json()
    assert body["total"] == 6
    assert len(body["items"]) == 3
    assert all(o["status"] == "completed" for o in body["items"])

    by_customer = client.get("/api/orders?customer_id=CUST-0002").json()
    assert {o["order_id"] for o in by_customer["items"]} == {"ORD-3", "ORD-8"}


def test_order_detail_includes_items(client):
    body = client.get("/api/orders/ORD-1").json()
    assert body["customer_name"] == "Asha Rao"
    assert body["items_total"] == 250.0
    assert len(body["items"]) == 2
    assert body["items"][0]["line_total"] == 200.0


def test_order_detail_404_envelope(client):
    resp = client.get("/api/orders/ORD-NOPE")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_data_quality_reports_every_trap(client, ingested):
    body = client.get("/api/data-quality").json()
    assert body["ingested"] is True
    assert body["run_id"] == ingested["run_id"]
    counts = body["issue_counts"]
    for expected in (
        "duplicate_exact",
        "duplicate_conflicting",
        "unknown_customer",
        "total_mismatch",
        "missing_email",
    ):
        assert counts[expected] == 1, expected
    # Filtering by type works.
    only = client.get("/api/data-quality?issue_type=unknown_customer").json()
    assert [i["issue_type"] for i in only["issues"]] == ["unknown_customer"]
