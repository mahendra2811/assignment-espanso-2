import { useEffect, useState } from "react";

type Bucket = {
  period_start: string;
  label: string;
  order_count: number;
  refund_count: number;
  gross_revenue: number;
  refund_total: number;
  net_revenue: number;
};

type RevenueResponse = {
  granularity: string;
  buckets: Bucket[];
  totals: {
    order_count: number;
    refund_count: number;
    gross_revenue: number;
    refund_total: number;
    net_revenue: number;
    avg_order_value: number;
  };
};

type Granularity = "day" | "week" | "month";

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export default function App() {
  const [granularity, setGranularity] = useState<Granularity>("week");
  const [data, setData] = useState<RevenueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [issueCount, setIssueCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/metrics/revenue?granularity=${granularity}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((d: RevenueResponse) => {
        if (!cancelled) setData(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [granularity]);

  useEffect(() => {
    fetch("/api/data-quality?limit=1")
      .then((r) => r.json())
      .then((d) => setIssueCount(d?.summary?.total_issues ?? null))
      .catch(() => setIssueCount(null));
  }, []);

  const maxNet = Math.max(1, ...(data?.buckets.map((b) => b.net_revenue) ?? []));

  return (
    <main className="page">
      <header>
        <h1>Revenue</h1>
        <p className="subtitle">
          Net revenue over time — cancelled orders excluded, refunds netted out.
        </p>
        {issueCount !== null && issueCount > 0 && (
          <p className="dq-banner">
            Ingest flagged {issueCount} data-quality issue{issueCount === 1 ? "" : "s"} in
            the feed — details at <code>/api/data-quality</code>.
          </p>
        )}
      </header>

      <div className="controls">
        {(["day", "week", "month"] as Granularity[]).map((g) => (
          <button
            key={g}
            className={g === granularity ? "active" : ""}
            onClick={() => setGranularity(g)}
          >
            {g}
          </button>
        ))}
      </div>

      {loading && <p className="state">Loading…</p>}
      {error && (
        <p className="state error">
          Could not load data: {error}. Is the API running on port 8000 and has
          the ingest been run?
        </p>
      )}

      {data && !loading && !error && (
        <>
          <section className="cards">
            <div className="card">
              <span className="card-label">Net revenue</span>
              <span className="card-value">{inr.format(data.totals.net_revenue)}</span>
            </div>
            <div className="card">
              <span className="card-label">Completed orders</span>
              <span className="card-value">{data.totals.order_count}</span>
            </div>
            <div className="card">
              <span className="card-label">Refunded</span>
              <span className="card-value">
                {inr.format(Math.abs(data.totals.refund_total))}
                <small> ({data.totals.refund_count})</small>
              </span>
            </div>
            <div className="card">
              <span className="card-label">Avg order value</span>
              <span className="card-value">{inr.format(data.totals.avg_order_value)}</span>
            </div>
          </section>

          <section className="chart" aria-label="Net revenue chart">
            {data.buckets.map((b) => (
              <div
                key={b.period_start}
                className="bar-wrap"
                title={`${b.label}: ${inr.format(b.net_revenue)} net (${b.order_count} orders)`}
              >
                <div
                  className="bar"
                  style={{ height: `${Math.max(2, (Math.max(0, b.net_revenue) / maxNet) * 100)}%` }}
                />
              </div>
            ))}
          </section>

          <table>
            <thead>
              <tr>
                <th>Period</th>
                <th>Orders</th>
                <th>Gross</th>
                <th>Refunds</th>
                <th>Net</th>
              </tr>
            </thead>
            <tbody>
              {data.buckets.map((b) => (
                <tr key={b.period_start}>
                  <td>{b.label}</td>
                  <td>{b.order_count}</td>
                  <td>{inr.format(b.gross_revenue)}</td>
                  <td>{b.refund_count > 0 ? inr.format(b.refund_total) : "—"}</td>
                  <td>{inr.format(b.net_revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
