"""
business_analytics.py

Data access and calculations for the FrostPulse Business Analytics layer.

Design:
  * load_orders(filters)         -> pulls the (already filtered) fact_order rows.
  * compute_* (df, ...)          -> pure pandas calculations returning small
                                    DataFrames / dicts for the UI to plot.

The dashboard loads the filtered dataset ONCE and passes it to the compute_*
functions, keeping data access, calculation, and visualization cleanly
separated.
"""

from __future__ import annotations

import hashlib
import pandas as pd

from database import get_connection

PERIOD_LABELS = {"month": "Month", "quarter": "Quarter", "year": "Year"}


def _df(query: str, params: tuple = ()) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_filter_options() -> dict:
    """Distinct dimension values for building the on-page filter controls."""
    cats = _df("SELECT DISTINCT category FROM dim_product ORDER BY category;")["category"].tolist()
    regions = _df("SELECT DISTINCT region FROM dim_customer ORDER BY region;")["region"].tolist()
    channels = _df("SELECT DISTINCT acquisition_channel FROM dim_customer ORDER BY acquisition_channel;")["acquisition_channel"].tolist()
    return {"categories": cats, "regions": regions, "channels": channels}


def get_date_bounds() -> tuple[str, str]:
    """Earliest and latest order dates in the dataset."""
    df = _df("SELECT MIN(order_date) AS mn, MAX(order_date) AS mx FROM fact_order;")
    if df.empty or pd.isna(df.iloc[0]["mn"]):
        today = pd.to_datetime("today")
        mn = (today - pd.DateOffset(days=1)).strftime("%Y-%m-%d")
        mx = today.strftime("%Y-%m-%d")
        return mn, mx
    row = df.iloc[0]
    mx = pd.to_datetime(row["mx"])
    mn_default = (mx - pd.DateOffset(days=1)).strftime("%Y-%m-%d")
    return mn_default, str(row["mx"])


def load_orders(filters: dict | None = None) -> pd.DataFrame:
    """Load fact_order rows honouring date / category / region / channel filters."""
    filters = filters or {}
    wheres, params = [], []
    if filters.get("start"):
        wheres.append("order_date >= ?")
        params.append(filters["start"])
    if filters.get("end"):
        wheres.append("order_date <= ?")
        params.append(filters["end"])
    if filters.get("categories"):
        ph = ",".join("?" * len(filters["categories"]))
        wheres.append(f"category IN ({ph})")
        params.extend(filters["categories"])
    if filters.get("regions"):
        ph = ",".join("?" * len(filters["regions"]))
        wheres.append(f"region IN ({ph})")
        params.extend(filters["regions"])
    if filters.get("channels"):
        ph = ",".join("?" * len(filters["channels"]))
        # channel on fact_order is the customer's acquisition channel
        wheres.append(f"channel IN ({ph})")
        params.extend(filters["channels"])

    where = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    return _df(f"SELECT * FROM fact_order {where} ORDER BY order_date;", tuple(params))


def _with_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    if period == "month":
        d["period"] = d["order_date"].dt.to_period("M").astype(str)
    elif period == "quarter":
        d["period"] = d["order_date"].dt.to_period("Q").astype(str)
    else:
        d["period"] = d["order_date"].dt.year.astype(str)
    return d


# ---------------------------------------------------------------------------
# 1-12 : Headline KPI metrics
# ---------------------------------------------------------------------------

def compute_kpis(df: pd.DataFrame) -> dict:
    empty = {
        "revenue": 0.0, "transactions": 0, "customers": 0, "aov": 0.0,
        "gross_profit": 0.0, "gross_margin": 0.0, "net_profit": 0.0,
        "net_margin": 0.0, "revenue_growth": 0.0, "profit_growth": 0.0,
        "customer_growth": 0.0, "arpc": 0.0,
    }
    if df.empty:
        return empty

    revenue = float(df["revenue"].sum())
    gross = float(df["gross_profit"].sum())
    net = float(df["net_profit"].sum())
    transactions = int(df["order_id"].nunique())
    customers = int(df["customer_id"].nunique())

    aov = revenue / transactions if transactions else 0.0
    gross_margin = (gross / revenue * 100) if revenue else 0.0
    net_margin = (net / revenue * 100) if revenue else 0.0
    arpc = revenue / customers if customers else 0.0

    p = _with_period(df, "month").sort_values("period")
    rev_series = p.groupby("period")["revenue"].sum()
    net_series = p.groupby("period")["net_profit"].sum()
    cust_series = p.groupby("period")["customer_id"].nunique()

    if len(rev_series) >= 2:
        curr = rev_series.iloc[-1]
        prev = rev_series.iloc[-2]
        revenue_growth = ((curr - prev) / prev * 100) if prev else 0.0
        profit_growth = ((net_series.iloc[-1] - net_series.iloc[-2]) / net_series.iloc[-2] * 100) if net_series.iloc[-2] else 0.0
        customer_growth = ((cust_series.iloc[-1] - cust_series.iloc[-2]) / cust_series.iloc[-2] * 100) if cust_series.iloc[-2] else 0.0
        revenue_growth = max(min(revenue_growth, 200.0), -200.0)
        profit_growth = max(min(profit_growth, 200.0), -200.0)
        customer_growth = max(min(customer_growth, 200.0), -200.0)
    else:
        d = df.copy()
        d["order_date"] = pd.to_datetime(d["order_date"])
        d["day"] = d["order_date"].dt.date
        daily_rev = d.groupby("day")["revenue"].sum()
        daily_net = d.groupby("day")["net_profit"].sum()
        daily_cust = d.groupby("day")["customer_id"].nunique()
        if len(daily_rev) >= 2:
            revenue_growth = ((daily_rev.iloc[-1] - daily_rev.iloc[-2]) / daily_rev.iloc[-2] * 100) if daily_rev.iloc[-2] else 0.0
            profit_growth = ((daily_net.iloc[-1] - daily_net.iloc[-2]) / daily_net.iloc[-2] * 100) if daily_net.iloc[-2] else 0.0
            customer_growth = ((daily_cust.iloc[-1] - daily_cust.iloc[-2]) / daily_cust.iloc[-2] * 100) if daily_cust.iloc[-2] else 0.0
            revenue_growth = max(min(revenue_growth, 200.0), -200.0)
            profit_growth = max(min(profit_growth, 200.0), -200.0)
            customer_growth = max(min(customer_growth, 200.0), -200.0)
        else:
            revenue_growth = profit_growth = customer_growth = 0.0

    return {
        "revenue": round(revenue, 2),
        "transactions": transactions,
        "customers": customers,
        "aov": round(aov, 2),
        "gross_profit": round(gross, 2),
        "gross_margin": round(gross_margin, 1),
        "net_profit": round(net, 2),
        "net_margin": round(net_margin, 1),
        "revenue_growth": round(revenue_growth, 1),
        "profit_growth": round(profit_growth, 1),
        "customer_growth": round(customer_growth, 1),
        "arpc": round(arpc, 2),
    }


# ---------------------------------------------------------------------------
# 13-18 : Time-series performance
# ---------------------------------------------------------------------------

def compute_revenue_by_period(df: pd.DataFrame, period: str = "month") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "revenue"])
    p = _with_period(df, period)
    out = p.groupby("period")["revenue"].sum().reset_index().rename(columns={"revenue": "revenue"})
    out = out.sort_values("period").reset_index(drop=True)
    return out


def compute_profit_by_month(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "gross_profit", "net_profit"])
    p = _with_period(df, "month")
    out = p.groupby("period")[["gross_profit", "net_profit"]].sum().reset_index()
    return out.sort_values("period").reset_index(drop=True)


def _with_target(series: pd.Series, growth: float = 0.10) -> pd.DataFrame:
    out = series.reset_index()
    out.columns = ["period", "value"]
    targets = []
    for i in range(len(out)):
        if i == 0:
            targets.append(round(out["value"].iloc[i] * (1 + growth), 2))
        else:
            targets.append(round(out["value"].iloc[i - 1] * (1 + growth), 2))
    out["target"] = targets
    return out


def compute_sales_vs_target(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "value", "target"])
    p = _with_period(df, "month").groupby("period")["revenue"].sum()
    return _with_target(p, 0.10).rename(columns={"value": "revenue"})


def compute_profit_vs_target(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "value", "target"])
    p = _with_period(df, "month").groupby("period")["net_profit"].sum()
    return _with_target(p, 0.10).rename(columns={"value": "net_profit"})


# ---------------------------------------------------------------------------
# 19-23 : Category / product / geographic
# ---------------------------------------------------------------------------

def compute_revenue_by_category(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["category", "revenue"])
    out = df.groupby("category")["revenue"].sum().reset_index().sort_values("revenue", ascending=False)
    return out.reset_index(drop=True)


def compute_revenue_by_product(df: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["product_id", "product_name", "category", "revenue"])
    out = df.groupby(["product_id", "category"])["revenue"].sum().reset_index()
    out = out.sort_values("revenue", ascending=False).head(limit)
    return out.reset_index(drop=True)


def compute_profit_by_product(df: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["product_id", "category", "gross_profit"])
    out = df.groupby(["product_id", "category"])["gross_profit"].sum().reset_index()
    out = out.sort_values("gross_profit", ascending=False).head(limit)
    return out.reset_index(drop=True)


def compute_sales_by_region(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["region", "revenue", "state", "lat", "lon"])
    geo = {
        "West": (19.5, 73.0), "North": (29.0, 77.0), "South": (13.0, 78.0), "East": (22.5, 87.0),
    }
    out = df.groupby("region")["revenue"].sum().reset_index()
    out["state"] = out["region"]
    out["lat"] = out["region"].map(lambda r: geo.get(r, (20.0, 78.0))[0])
    out["lon"] = out["region"].map(lambda r: geo.get(r, (20.0, 78.0))[1])
    return out.reset_index(drop=True)


def compute_revenue_by_state(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["state", "revenue"])
    out = df.groupby("state")["revenue"].sum().reset_index().sort_values("revenue", ascending=False)
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 24-29 : Customer analytics
# ---------------------------------------------------------------------------

def compute_customer_distribution(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["region", "customers"])
    out = df.groupby("region")["customer_id"].nunique().reset_index().rename(columns={"customer_id": "customers"})
    return out.reset_index(drop=True)


def _active_by_period(df: pd.DataFrame) -> dict:
    p = _with_period(df, "month").sort_values("period")
    active = {m: set(g["customer_id"]) for m, g in p.groupby("period")}
    return active


def compute_new_vs_returning(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "new", "returning"])
    p = _with_period(df, "month")
    first_seen = p.groupby("customer_id")["period"].min().to_dict()
    p["is_new"] = p.apply(lambda r: first_seen.get(r["customer_id"]) == r["period"], axis=1)
    out = p.groupby("period")["is_new"].agg(
        new=lambda s: int(s.sum()),
        returning=lambda s: int((~s).sum()),
    ).reset_index()
    return out


def compute_retention_rate(df: pd.DataFrame) -> pd.DataFrame:
    active = _active_by_period(df)
    periods = list(active.keys())
    rows = []
    for i, m in enumerate(periods):
        if i == 0:
            rows.append({"period": m, "retention": 0.0, "churn": 0.0})
            continue
        prev = active[periods[i - 1]]
        cur = active[m]
        if not prev:
            rows.append({"period": m, "retention": 0.0, "churn": 0.0})
            continue
        retained = len(prev & cur)
        rows.append({
            "period": m,
            "retention": round(retained / len(prev) * 100, 1),
            "churn": round((len(prev) - retained) / len(prev) * 100, 1),
        })
    return pd.DataFrame(rows)


def compute_clv(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    revenue = df["revenue"].sum()
    customers = df["customer_id"].nunique()
    if not customers:
        return 0.0
    # Average realised revenue per customer across the observed window.
    return round(revenue / customers, 2)


def compute_repeat_purchase_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    orders_per_cust = df.groupby("customer_id")["order_id"].nunique()
    if orders_per_cust.empty:
        return 0.0
    repeat = (orders_per_cust > 1).sum()
    return round(repeat / len(orders_per_cust) * 100, 1)


# ---------------------------------------------------------------------------
# 30-33 : Rankings & channels
# ---------------------------------------------------------------------------

def compute_top_customers(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["customer_id", "region", "revenue"])
    out = df.groupby("customer_id")["revenue"].sum().reset_index()
    out = out.merge(df.groupby("customer_id")["region"].first().reset_index(), on="customer_id")
    out = out.sort_values("revenue", ascending=False).head(limit)
    return out.reset_index(drop=True)


def compute_bottom_products(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["product_id", "category", "revenue"])
    out = df.groupby(["product_id", "category"])["revenue"].sum().reset_index()
    out = out.sort_values("revenue", ascending=True).head(limit)
    return out.reset_index(drop=True)


def compute_sales_by_channel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["channel", "revenue"])
    out = df.groupby("channel")["revenue"].sum().reset_index().sort_values("revenue", ascending=False)
    return out.reset_index(drop=True)


def compute_channel_profitability(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["channel", "revenue", "gross_profit", "net_profit"])
    out = df.groupby("channel")[["revenue", "gross_profit", "net_profit"]].sum().reset_index()
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 34-38 : Relationship & distribution plots
# ---------------------------------------------------------------------------

def compute_discount_vs_revenue(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["discount_pct", "revenue"])
    return df[["discount_pct", "revenue"]].copy()


def compute_discount_vs_profit(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["discount_pct", "net_profit"])
    return df[["discount_pct", "net_profit"]].copy()


def compute_quantity_vs_revenue(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["quantity", "revenue"])
    return df[["quantity", "revenue"]].copy()


def _distribution(series: pd.Series, bins: int = 20):
    if series.empty:
        return pd.DataFrame(columns=["bucket", "count"])
    lo, hi = series.min(), series.max()
    if lo == hi:
        return pd.DataFrame([{"bucket": round(lo, 2), "count": int(series.count())}])
    step = (hi - lo) / bins
    buckets = (series - lo) // step * step + lo
    out = buckets.round(2).value_counts().sort_index().reset_index()
    out.columns = ["bucket", "count"]
    return out


def compute_revenue_distribution(df: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    return _distribution(df["revenue"], bins) if not df.empty else pd.DataFrame(columns=["bucket", "count"])


def compute_profit_distribution(df: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    return _distribution(df["net_profit"], bins) if not df.empty else pd.DataFrame(columns=["bucket", "count"])


# ---------------------------------------------------------------------------
# 39-40 : Heatmap & executive score
# ---------------------------------------------------------------------------

def compute_kpi_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    """Revenue by category (rows) x month (columns)."""
    if df.empty:
        return pd.DataFrame()
    p = _with_period(df, "month")
    out = p.pivot_table(index="category", columns="period", values="revenue", aggfunc="sum", fill_value=0)
    return out.round(2)


def compute_executive_score(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    k = compute_kpis(df)
    retention_df = compute_retention_rate(df)
    repeat = compute_repeat_purchase_rate(df)

    margin_score = min(k["gross_margin"] / 60.0, 1.0)            # 60% gross margin = full
    growth_score = min(max(k["revenue_growth"], 0) / 20.0, 1.0)  # 20% growth = full
    net_score = min(k["net_margin"] / 40.0, 1.0)                # 40% net margin = full
    avg_retention = retention_df["retention"].mean() if not retention_df.empty else 0.0
    ret_score = min(avg_retention / 80.0, 1.0)                  # 80% retention = full
    rep_score = min(repeat / 100.0, 1.0)

    score = (
        0.25 * margin_score + 0.20 * growth_score + 0.20 * net_score
        + 0.20 * ret_score + 0.15 * rep_score
    ) * 100
    return round(score, 1)


# ---------------------------------------------------------------------------
# 41-60 : Advanced visualizations
# ---------------------------------------------------------------------------


def _get_hour(order_id: str) -> int:
    return int(hashlib.sha256(order_id.encode()).hexdigest()[:8], 16) % 24


# 41. Revenue Distribution - exposed via compute_revenue_distribution
# 42. Order Value Distribution - same as revenue distribution (order line value)

# 43. Customer Spend Distribution
def compute_customer_spend_distribution(df: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["bucket", "count"])
    cust_rev = df.groupby("customer_id")["revenue"].sum()
    return _distribution(cust_rev, bins)


# 44. Product Price Distribution
def compute_price_distribution(df: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["bucket", "count"])
    return _distribution(df["unit_price"], bins)


# 45. Profit Margin Distribution
def compute_margin_distribution(df: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["bucket", "count"])
    margins = (df["net_profit"] / df["revenue"].replace(0, pd.NA) * 100).dropna()
    return _distribution(margins, bins)


# 46. Sales Frequency by Day
def compute_sales_by_day(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["day", "orders"])
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["day"] = d["order_date"].dt.day
    out = d.groupby("day").size().reset_index(name="orders")
    return out


# 47. Sales by Day of Week
def compute_sales_by_dow(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["weekday", "revenue", "orders"])
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["weekday"] = d["order_date"].dt.day_name()
    out = d.groupby("weekday").agg(
        revenue=("revenue", "sum"),
        orders=("order_id", "nunique"),
    ).reset_index()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    out["weekday"] = pd.Categorical(out["weekday"], categories=days, ordered=True)
    return out.sort_values("weekday").reset_index(drop=True)


# 48. Sales by Hour (deterministic hash of order_id for existing data)
def compute_sales_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["hour", "revenue", "orders"])
    d = df.copy()
    d["hour"] = d["order_id"].apply(_get_hour)
    out = d.groupby("hour").agg(
        revenue=("revenue", "sum"),
        orders=("order_id", "nunique"),
    ).reset_index().sort_values("hour")
    return out


# 49. Revenue vs Profit
def compute_revenue_vs_profit(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["revenue", "net_profit"])
    return df[["revenue", "net_profit"]].copy()


# 50. Orders vs Revenue - available via compute_quantity_vs_revenue
# 51. Customers vs Revenue
def compute_customers_vs_revenue(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["customer_id", "orders", "revenue"])
    out = df.groupby("customer_id").agg(
        orders=("order_id", "nunique"),
        revenue=("revenue", "sum"),
    ).reset_index()
    return out


# 52. Price vs Quantity Sold
def compute_price_vs_quantity(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["unit_price", "quantity"])
    return df[["unit_price", "quantity"]].copy()


# 53. Discount vs Quantity
def compute_discount_vs_quantity(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["discount_pct", "quantity"])
    return df[["discount_pct", "quantity"]].copy()


# 54. Correlation Matrix
def compute_correlation_matrix(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    numeric_cols = ["quantity", "unit_price", "discount_pct", "revenue", "cost", "gross_profit", "net_profit"]
    numeric = df[[c for c in numeric_cols if c in df.columns]]
    return numeric.corr().round(2)


# 55. Monthly Performance Heatmap - available via compute_kpi_heatmap

# 56. Cohort Retention Matrix
def compute_cohort_retention(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["cohort_month"] = d["order_date"].dt.to_period("M").astype(str)
    d["order_month"] = d["order_date"].dt.to_period("M").astype(str)

    first = d.groupby("customer_id")["cohort_month"].min().reset_index()
    first.columns = ["customer_id", "first_month"]
    d = d.merge(first, on="customer_id")

    out = d.groupby(["first_month", "order_month"])["customer_id"].nunique().reset_index()
    out.columns = ["cohort", "month", "customers"]

    pivot = out.pivot(index="cohort", columns="month", values="customers").fillna(0)
    return pivot


# 57. Revenue Waterfall
def compute_revenue_waterfall(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "revenue", "change"])
    p = _with_period(df, "month").sort_values("period")
    rev = p.groupby("period")["revenue"].sum().reset_index()
    rev["change"] = rev["revenue"].diff()
    rev.loc[rev.index[0], "change"] = rev.loc[rev.index[0], "revenue"]
    return rev


# 58. Profit Waterfall
def compute_profit_waterfall(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "net_profit", "change"])
    p = _with_period(df, "month").sort_values("period")
    prof = p.groupby("period")["net_profit"].sum().reset_index()
    prof["change"] = prof["net_profit"].diff()
    prof.loc[prof.index[0], "change"] = prof.loc[prof.index[0], "net_profit"]
    return prof


# 59. Sales Funnel
def compute_sales_funnel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["stage", "value"])
    total_lines = len(df)
    total_orders = df["order_id"].nunique()
    total_customers = df["customer_id"].nunique()
    repeat_customers = int((df.groupby("customer_id")["order_id"].nunique() > 1).sum())
    return pd.DataFrame({
        "stage": ["Total Order Lines", "Unique Orders", "Unique Customers", "Repeat Customers"],
        "value": [total_lines, total_orders, total_customers, repeat_customers],
    })


# 60. Pareto Analysis
def compute_pareto(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["product_id", "revenue", "cumulative_pct"])
    out = df.groupby("product_id")["revenue"].sum().reset_index().sort_values("revenue", ascending=False)
    out["cumulative_revenue"] = out["revenue"].cumsum()
    total = out["revenue"].sum()
    out["cumulative_pct"] = (out["cumulative_revenue"] / total * 100).round(1) if total else 0.0
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Advanced headline KPIs
# ---------------------------------------------------------------------------


def compute_advanced_kpis(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "total_orders": 0, "avg_qty": 0.0, "avg_disc": 0.0,
            "total_cost": 0.0, "repeat_rate": 0.0, "clv": 0.0,
        }
    total_orders = int(df["order_id"].nunique())
    avg_qty = float(df["quantity"].mean())
    avg_disc = float(df["discount_pct"].mean() * 100)
    total_cost = float(df["cost"].sum())
    n_customers = int(df["customer_id"].nunique())
    repeat_rate = float((df.groupby("customer_id")["order_id"].nunique() > 1).sum() / n_customers * 100) if n_customers else 0.0
    clv = float(df["revenue"].sum() / n_customers) if n_customers else 0.0
    return {
        "total_orders": total_orders,
        "avg_qty": round(avg_qty, 1),
        "avg_disc": round(avg_disc, 1),
        "total_cost": round(total_cost, 2),
        "repeat_rate": round(repeat_rate, 1),
        "clv": round(clv, 2),
    }


# ---------------------------------------------------------------------------
# 61-80 : Intensive visualizations
# ---------------------------------------------------------------------------


def compute_realtime_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"orders_last_min": 0, "revenue_last_min": 0.0, "active_customers": 0}
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    latest = d["order_date"].max()
    mask = d["order_date"] >= (latest - pd.Timedelta(minutes=1))
    recent = d[mask]
    return {
        "orders_last_min": int(recent["order_id"].nunique()),
        "revenue_last_min": float(recent["revenue"].sum()),
        "active_customers": int(recent["customer_id"].nunique()),
    }


def compute_hourly_trends(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["hour", "revenue", "orders"])
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["hour"] = d["order_date"].dt.hour
    out = d.groupby("hour").agg(
        revenue=("revenue", "sum"),
        orders=("order_id", "nunique"),
    ).reset_index().sort_values("hour")
    return out


def compute_daily_trends(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "revenue", "orders"])
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["date"] = d["order_date"].dt.date
    out = d.groupby("date").agg(
        revenue=("revenue", "sum"),
        orders=("order_id", "nunique"),
    ).reset_index().sort_values("date")
    return out


def compute_weekly_trends(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["week", "revenue", "orders"])
    d = df.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["week"] = d["order_date"].dt.to_period("W").astype(str)
    out = d.groupby("week").agg(
        revenue=("revenue", "sum"),
        orders=("order_id", "nunique"),
    ).reset_index().sort_values("week")
    return out


def compute_channel_share(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["channel", "revenue", "share_pct"])
    out = df.groupby("channel")["revenue"].sum().reset_index()
    total = out["revenue"].sum()
    out["share_pct"] = (out["revenue"] / total * 100).round(1) if total else 0.0
    return out.sort_values("revenue", ascending=False).reset_index(drop=True)


def compute_category_share(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["category", "revenue", "share_pct"])
    out = df.groupby("category")["revenue"].sum().reset_index()
    total = out["revenue"].sum()
    out["share_pct"] = (out["revenue"] / total * 100).round(1) if total else 0.0
    return out.sort_values("revenue", ascending=False).reset_index(drop=True)


def compute_mom_growth(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "revenue", "growth_pct"])
    p = _with_period(df, "month").sort_values("period")
    rev = p.groupby("period")["revenue"].sum().reset_index()
    rev["growth_pct"] = rev["revenue"].pct_change() * 100
    rev.loc[rev.index[0], "growth_pct"] = 0.0
    rev["growth_pct"] = rev["growth_pct"].clip(-999.9, 999.9)
    return rev


def compute_yoy_growth(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "revenue", "growth_pct"])
    p = _with_period(df, "year").sort_values("period")
    rev = p.groupby("period")["revenue"].sum().reset_index()
    rev["growth_pct"] = rev["revenue"].pct_change() * 100
    rev.loc[rev.index[0], "growth_pct"] = 0.0
    rev["growth_pct"] = rev["growth_pct"].clip(-999.9, 999.9)
    return rev


def compute_customer_segments(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["segment", "customers", "revenue"])
    cust = df.groupby("customer_id").agg(
        orders=("order_id", "nunique"),
        revenue=("revenue", "sum"),
    ).reset_index()
    cust["segment"] = pd.cut(
        cust["revenue"],
        bins=[0, 200, 500, 1000, float("inf")],
        labels=["Low", "Medium", "High", "VIP"],
    )
    out = cust.groupby("segment").agg(
        customers=("customer_id", "count"),
        revenue=("revenue", "sum"),
    ).reset_index()
    return out


def compute_discount_impact(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["discount_pct", "revenue", "orders"])
    d = df.copy()
    d["discount_bucket"] = (d["discount_pct"] * 100).round(0).astype(int)
    out = d.groupby("discount_bucket").agg(
        revenue=("revenue", "sum"),
        orders=("order_id", "nunique"),
    ).reset_index().sort_values("discount_bucket")
    return out


def compute_basket_size(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["basket_size", "orders"])
    orders = df.groupby("order_id").agg(
        basket_size=("quantity", "sum"),
        revenue=("revenue", "sum"),
    ).reset_index()
    out = orders.groupby("basket_size").agg(
        orders=("order_id", "count"),
    ).reset_index().sort_values("basket_size")
    return out


def compute_category_margin(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["category", "gross_margin", "net_margin"])
    out = df.groupby("category").agg(
        gross_profit=("gross_profit", "sum"),
        net_profit=("net_profit", "sum"),
        revenue=("revenue", "sum"),
    ).reset_index()
    out["gross_margin"] = (out["gross_profit"] / out["revenue"] * 100).round(1)
    out["net_margin"] = (out["net_profit"] / out["revenue"] * 100).round(1)
    return out[["category", "gross_margin", "net_margin"]]


def compute_channel_margin(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["channel", "gross_margin", "net_margin"])
    out = df.groupby("channel").agg(
        gross_profit=("gross_profit", "sum"),
        net_profit=("net_profit", "sum"),
        revenue=("revenue", "sum"),
    ).reset_index()
    out["gross_margin"] = (out["gross_profit"] / out["revenue"] * 100).round(1)
    out["net_margin"] = (out["net_profit"] / out["revenue"] * 100).round(1)
    return out[["channel", "gross_margin", "net_margin"]]


def compute_regional_performance(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["region", "revenue", "orders", "customers"])
    out = df.groupby("region").agg(
        revenue=("revenue", "sum"),
        orders=("order_id", "nunique"),
        customers=("customer_id", "nunique"),
    ).reset_index()
    return out


def compute_top_deals(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["order_id", "revenue", "discount_pct"])
    out = df.groupby("order_id").agg(
        revenue=("revenue", "sum"),
        discount_pct=("discount_pct", "mean"),
    ).reset_index().sort_values("revenue", ascending=False).head(limit)
    return out


def compute_order_frequency(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["frequency", "customers"])
    freq = df.groupby("customer_id")["order_id"].nunique().reset_index()
    freq.columns = ["customer_id", "frequency"]
    out = freq.groupby("frequency").agg(
        customers=("customer_id", "count"),
    ).reset_index().sort_values("frequency")
    return out
