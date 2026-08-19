"""
business_dashboard.py

Power BI-style executive dashboard for the FrostPulse Business Analytics
layer. Renders 80+ KPIs / visualizations across eight pages, with
on-page filters (date range, category, region, channel), cross-cutting KPI
cards, tooltips, an export button, auto-refresh every 60 seconds,
and a professional light theme.

Visualization only: all data access and calculations live in
business_analytics.py. This module calls those functions and plots the
returned DataFrames.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import business_analytics as ba

# ---------------------------------------------------------------------------
# Professional light theme tokens
# ---------------------------------------------------------------------------

NAVY = "#0A1F33"
TEXT = "#1A2433"
MUTED = "#64748B"
ACCENT = "#1F6FEB"
CARD_BG = "#FFFFFF"
BORDER = "#E2E8F0"
PANEL = "#F8FAFC"
POS = "#16A34A"
NEG = "#DC2626"

PALETTE = ["#1F6FEB", "#0EA5E9", "#14B8A6", "#6366F1", "#F59E0B", "#8B5CF6", "#EC4899", "#10B981"]

BD_CSS = """
<style>
    .bd-hero { 
        background: linear-gradient(135deg, #0A1F33 0%, #1E3A5F 100%); 
        padding: 1.4rem 1.8rem; 
        border-radius: 16px; 
        margin-bottom: 1.2rem; 
        box-shadow: 0 8px 24px rgba(0,0,0,0.2);
    }
    .bd-title { font-size: 2.4rem; font-weight: 800; color: #FFFFFF; margin: 0; letter-spacing: -0.02em; }
    .bd-sub { font-size: 1.0rem; color: #E2E8F0; margin-top: 0.3rem; font-weight: 500; }
    .bd-section { 
        font-size: 1.1rem; font-weight: 700; color: #FFFFFF;
        background: linear-gradient(90deg, rgba(31, 111, 235, 0.2) 0%, transparent 100%);
        border-left: 4px solid #1F6FEB; 
        padding: 0.6rem 1rem; 
        border-radius: 0 10px 10px 0;
        margin: 1.8rem 0 0.8rem 0; 
    }
    .bd-kpi-title { font-size: 0.75rem; color: #64748B; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.04em; }
    .bd-kpi-value { font-size: 1.6rem; color: #0A1F33; font-weight: 800; margin-top: 0.3rem; line-height: 1.1; }
    .bd-filterbar { 
        background: #FFFFFF; 
        border: 1px solid #E2E8F0; 
        border-radius: 14px; 
        padding: 1rem 1.2rem; 
        margin: 1rem 0 0.6rem 0; 
        box-shadow: 0 2px 8px rgba(16,24,40,0.06); 
    }
    .bd-footer { text-align: center; color: #64748B; font-size: 0.85rem; margin-top: 2.5rem;
        padding-top: 1rem; border-top: 1px solid #E2E8F0; }
    div[data-testid="stTabs"] button { 
        font-weight: 600; 
        border-radius: 8px 8px 0 0;
        padding: 0.6rem 1.2rem;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        background: linear-gradient(180deg, #1F6FEB 0%, #0A1F33 100%);
        color: white;
    }
</style>
"""


# ---------------------------------------------------------------------------
# Reusable components
# ---------------------------------------------------------------------------

def _fmt_currency(v: float) -> str:
    return f"{v:,.0f}"


def kpi_card(title: str, value: str, delta: float | None = None, positive: bool | None = None) -> str:
    if delta is not None:
        is_pos = positive if positive is not None else delta >= 0
        color = POS if is_pos else NEG
        arrow = "▲" if delta >= 0 else "▼"
        delta_html = (
            f'<div style="font-size:0.8rem;color:{color};font-weight:700;margin-top:0.2rem;">'
            f'{arrow} {abs(delta):.1f}%</div>'
        )
    else:
        delta_html = ""
    return f"""
    <div style="background:{CARD_BG};border:1px solid {BORDER};border-radius:14px;
                padding:1rem 1.1rem;box-shadow:0 4px 12px rgba(16,24,40,0.08);height:100%;
                transition: transform 0.2s, box-shadow 0.2s;"
         onmouseover="this.style.transform='translateY(-3px)';this.style.boxShadow='0 8px 20px rgba(16,24,40,0.12)'"
         onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 4px 12px rgba(16,24,40,0.08)'">
      <div class="bd-kpi-title">{title}</div>
      <div class="bd-kpi-value">{value}</div>
      {delta_html}
    </div>"""


def kpi_row(items: list[tuple], ncols: int = 4):
    cols = st.columns(ncols)
    for i, it in enumerate(items):
        with cols[i % ncols]:
            st.markdown(kpi_card(*it), unsafe_allow_html=True)


def section(title: str):
    st.markdown(f'<div class="bd-section">{title}</div>', unsafe_allow_html=True)


def style_fig(fig: go.Figure, height: int = 360, showlegend: bool = True) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=10, r=10, t=24, b=10),
        font=dict(color=TEXT, family="Inter, Segoe UI, sans-serif"),
        title_font=dict(size=13, color=NAVY),
        showlegend=showlegend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor="#EEF2F7", zeroline=False)
    fig.update_yaxes(gridcolor="#EEF2F7", zeroline=False)
    return fig


def render_chart(fig: go.Figure, key: str, height: int = 360, showlegend: bool = True):
    fig = style_fig(fig, height=height, showlegend=showlegend)
    st.plotly_chart(fig, use_container_width=True, key=key)


def empty_state(msg: str = "No data for the current filters."):
    st.info(msg)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def render_filters() -> dict:
    opts = ba.get_filter_options()
    mn, mx = ba.get_date_bounds()

    with st.container():
        st.markdown('<div class="bd-filterbar">', unsafe_allow_html=True)
        r1 = st.columns([1, 1, 1, 1])
        start = r1[0].date_input("Start date", value=pd.to_datetime(mn), key="bd_start")
        end = r1[1].date_input("End date", value=pd.to_datetime(mx), key="bd_end")
        cats = r1[2].multiselect("Category", opts["categories"], default=opts["categories"], key="bd_cat")
        regions = r1[3].multiselect("Region", opts["regions"], default=opts["regions"], key="bd_reg")
        r2 = st.columns([1, 1, 2])
        channels = r2[0].multiselect("Channel", opts["channels"], default=opts["channels"], key="bd_chan")
        r2[1].write("")  # spacer
        r2[2].write("")  # spacer
        st.markdown("</div>", unsafe_allow_html=True)

    return {
        "start": start.strftime("%Y-%m-%d") if hasattr(start, "strftime") else str(start),
        "end": end.strftime("%Y-%m-%d") if hasattr(end, "strftime") else str(end),
        "categories": cats,
        "regions": regions,
        "channels": channels,
    }


# ---------------------------------------------------------------------------
# Page 1 - Executive Overview
# ---------------------------------------------------------------------------

def page_executive(df: pd.DataFrame, k: dict):
    rt = ba.compute_realtime_metrics(df)
    kpi_row([
        ("Total Revenue", f"${_fmt_currency(k['revenue'])}", k["revenue_growth"], True),
        ("Total Transactions", f"{k['transactions']:,}", None, None),
        ("Total Customers", f"{k['customers']:,}", k["customer_growth"], True),
        ("Avg Order Value", f"${_fmt_currency(k['aov'])}", None, None),
        ("Orders (Last Min)", f"{rt['orders_last_min']:,}", None, None),
        ("Revenue (Last Min)", f"${_fmt_currency(rt['revenue_last_min'])}", None, None),
    ])
    kpi_row([
        ("Gross Profit", f"${_fmt_currency(k['gross_profit'])}", None, None),
        ("Gross Margin %", f"{k['gross_margin']}%", None, None),
        ("Net Profit", f"${_fmt_currency(k['net_profit'])}", k["profit_growth"], True),
        ("Net Margin %", f"{k['net_margin']}%", None, None),
        ("Active Customers (Last Min)", f"{rt['active_customers']:,}", None, None),
        ("Customer Lifetime Value", f"${_fmt_currency(k['arpc'])}", None, None),
    ])
    kpi_row([
        ("Revenue Growth %", f"{k['revenue_growth']}%", None, None),
        ("Profit Growth %", f"{k['profit_growth']}%", None, None),
        ("Customer Growth %", f"{k['customer_growth']}%", None, None),
        ("Avg Revenue / Customer", f"${_fmt_currency(k['arpc'])}", None, None),
        ("Total Cost", f"${_fmt_currency(ba.compute_advanced_kpis(df)['total_cost'])}", None, None),
        ("Repeat Purchase Rate", f"{ba.compute_advanced_kpis(df)['repeat_rate']}%", None, None),
    ])

    section("Revenue Distribution")
    rev_dist = ba.compute_revenue_distribution(df)
    if not rev_dist.empty:
        fig = px.histogram(rev_dist, x="bucket", y="count", nbins=25,
                          labels={"bucket": "Revenue ($)", "count": "Order Lines"})
        render_chart(fig, "exec_rev_dist", height=340, showlegend=False)
    else:
        empty_state()

    c1, c2 = st.columns(2)
    with c1:
        section("Channel Revenue Share")
        chan_perf = ba.compute_channel_share(df)
        if not chan_perf.empty:
            fig = px.pie(chan_perf, names="channel", values="revenue", hole=0.5,
                        color_discrete_sequence=PALETTE)
            render_chart(fig, "exec_chan_pie", height=340)
        else:
            empty_state()
    with c2:
        section("Profit by Category")
        cat_profit = df.groupby("category")["net_profit"].sum().reset_index().sort_values("net_profit", ascending=True)
        if not cat_profit.empty:
            fig = px.bar(cat_profit, x="net_profit", y="category", orientation="h",
                        color="net_profit", color_continuous_scale="Blues",
                        labels={"net_profit": "Net Profit ($)", "category": "Category"})
            render_chart(fig, "exec_cat_profit", height=340, showlegend=False)
        else:
            empty_state()

    c3, c4 = st.columns(2)
    with c3:
        section("Daily Revenue Trend")
        daily = ba.compute_daily_trends(df)
        if not daily.empty:
            fig = px.line(daily, x="date", y="revenue", markers=True,
                         labels={"date": "Date", "revenue": "Revenue ($)"})
            render_chart(fig, "exec_daily_rev", height=320)
        else:
            empty_state()
    with c4:
        section("Weekly Revenue Trend")
        weekly = ba.compute_weekly_trends(df)
        if not weekly.empty:
            fig = px.bar(weekly, x="week", y="revenue", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"week": "Week", "revenue": "Revenue ($)"})
            render_chart(fig, "exec_weekly_rev", height=320, showlegend=False)
        else:
            empty_state()

    section("Channel & Category Performance")
    c3, c4 = st.columns(2)
    with c3:
        chan_perf = ba.compute_channel_share(df)
        if not chan_perf.empty:
            fig = px.pie(chan_perf, names="channel", values="revenue", hole=0.5,
                        color_discrete_sequence=PALETTE)
            render_chart(fig, "exec_chan_pie", height=340)
        else:
            empty_state()
    with c4:
        cat_perf = ba.compute_category_share(df)
        if not cat_perf.empty:
            fig = px.pie(cat_perf, names="category", values="revenue", hole=0.5,
                        color_discrete_sequence=PALETTE)
            render_chart(fig, "exec_cat_pie", height=340)
        else:
            empty_state()

    section("Customer Segments")
    seg = ba.compute_customer_segments(df)
    if not seg.empty:
        fig = px.bar(seg, x="segment", y="customers", color="revenue",
                    color_continuous_scale="Blues",
                    labels={"segment": "Segment", "customers": "Customers"})
        render_chart(fig, "exec_segments", height=320, showlegend=False)
    else:
        empty_state()

    section("Revenue Distribution")
    rev_dist = ba.compute_revenue_distribution(df)
    if not rev_dist.empty:
        fig = px.histogram(rev_dist, x="bucket", y="count", nbins=25,
                          labels={"bucket": "Revenue ($)", "count": "Order Lines"})
        render_chart(fig, "exec_rev_dist", height=340, showlegend=False)
    else:
        empty_state()

    section("Executive Performance Score")
    score = ba.compute_executive_score(df)
    gauge_color = POS if score >= 70 else (ACCENT if score >= 50 else NEG)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, number={"suffix": " / 100", "font": {"color": NAVY}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": MUTED},
            "bar": {"color": gauge_color}, "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [
                {"range": [0, 50], "color": "rgba(220,38,38,0.18)"},
                {"range": [50, 70], "color": "rgba(31,111,235,0.18)"},
                {"range": [70, 100], "color": "rgba(22,163,74,0.18)"},
            ],
        },
    ))
    render_chart(fig, "exec_score", height=320, showlegend=False)


# ---------------------------------------------------------------------------
# Page 2 - Sales Analytics
# ---------------------------------------------------------------------------

def page_sales(df: pd.DataFrame):
    section("Channel Revenue Share")
    chan = ba.compute_sales_by_channel(df)
    if not chan.empty:
        fig = px.pie(chan, names="channel", values="revenue", hole=0.5,
                     color_discrete_sequence=PALETTE)
        render_chart(fig, "sales_chan_pie", height=360)
    else:
        empty_state()

    c1, c2 = st.columns(2)
    with c1:
        section("Revenue by Quarter")
        rev_q = ba.compute_revenue_by_period(df, "quarter")
        if not rev_q.empty:
            fig = px.bar(rev_q, x="period", y="revenue", color_discrete_sequence=[ACCENT],
                         labels={"period": "Quarter", "revenue": "Revenue ($)"})
            render_chart(fig, "sales_qtr", height=320, showlegend=False)
        else:
            empty_state()
    with c2:
        section("Revenue by Year")
        rev_y = ba.compute_revenue_by_period(df, "year")
        if not rev_y.empty:
            fig = px.bar(rev_y, x="period", y="revenue", color_discrete_sequence=["#0EA5E9"],
                         labels={"period": "Year", "revenue": "Revenue ($)"})
            render_chart(fig, "sales_year", height=320, showlegend=False)
        else:
            empty_state()

    section("Sales vs Target")
    svt = ba.compute_sales_vs_target(df)
    if not svt.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=svt["period"], y=svt["revenue"], name="Actual", marker_color=ACCENT))
        fig.add_trace(go.Scatter(x=svt["period"], y=svt["target"], name="Target",
                                 mode="lines+markers", line=dict(color=POS, dash="dash")))
        render_chart(fig, "sales_target", height=360)
    else:
        empty_state()

    c3, c4 = st.columns(2)
    with c3:
        section("Revenue Contribution by Category")
        cat = ba.compute_revenue_by_category(df)
        if not cat.empty:
            fig = px.treemap(cat, path=["category"], values="revenue",
                             color="revenue", color_continuous_scale="Blues",
                             labels={"revenue": "Revenue ($)"})
            render_chart(fig, "sales_treemap", height=360, showlegend=False)
        else:
            empty_state()
    with c4:
        section("Revenue by Channel")
        chan = ba.compute_sales_by_channel(df)
        if not chan.empty:
            fig = px.pie(chan, names="channel", values="revenue", hole=0.5,
                         color_discrete_sequence=PALETTE)
            render_chart(fig, "sales_channel", height=360)
        else:
            empty_state()

    section("Revenue by Product (Top 15)")
    prod = ba.compute_revenue_by_product(df, limit=15)
    if not prod.empty:
        fig = px.bar(prod, x="revenue", y="product_id", orientation="h",
                     color="revenue", color_continuous_scale="Blues",
                     labels={"revenue": "Revenue ($)", "product_id": "Product"})
        fig.update_layout(yaxis=dict(autorange="reversed"))
        render_chart(fig, "sales_product", height=420, showlegend=False)
    else:
        empty_state()

    section("Daily & Weekly Sales Trends")
    c5, c6 = st.columns(2)
    with c5:
        daily = ba.compute_daily_trends(df)
        if not daily.empty:
            fig = px.line(daily, x="date", y="revenue", markers=True,
                         labels={"date": "Date", "revenue": "Revenue ($)"})
            render_chart(fig, "sales_daily", height=320)
        else:
            empty_state()
    with c6:
        weekly = ba.compute_weekly_trends(df)
        if not weekly.empty:
            fig = px.bar(weekly, x="week", y="revenue", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"week": "Week", "revenue": "Revenue ($)"})
            render_chart(fig, "sales_weekly", height=320, showlegend=False)
        else:
            empty_state()

    section("Channel Share & Performance")
    chan_perf = ba.compute_channel_share(df)
    if not chan_perf.empty:
        c7, c8 = st.columns(2)
        with c7:
            fig = px.pie(chan_perf, names="channel", values="revenue", hole=0.5,
                        color_discrete_sequence=PALETTE)
            render_chart(fig, "sales_chan_pie", height=340)
        with c8:
            fig = px.bar(chan_perf, x="channel", y="revenue", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"channel": "Channel", "revenue": "Revenue ($)"})
            render_chart(fig, "sales_chan_bar", height=340, showlegend=False)
    else:
        empty_state()

    section("Discount Impact on Revenue")
    disc_impact = ba.compute_discount_impact(df)
    if not disc_impact.empty:
        c9, c10 = st.columns(2)
        with c9:
            fig = px.bar(disc_impact, x="discount_bucket", y="revenue",
                        labels={"discount_bucket": "Discount %", "revenue": "Revenue ($)"})
            render_chart(fig, "sales_disc_rev", height=320, showlegend=False)
        with c10:
            fig = px.line(disc_impact, x="discount_bucket", y="orders", markers=True,
                         labels={"discount_bucket": "Discount %", "orders": "Orders"})
            render_chart(fig, "sales_disc_ord", height=320)
    else:
        empty_state()


# ---------------------------------------------------------------------------
# Page 3 - Customer Analytics
# ---------------------------------------------------------------------------

def page_customer(df: pd.DataFrame, k: dict):
    kpi_row([
        ("Total Customers", f"{k['customers']:,}", k["customer_growth"], True),
        ("Avg Revenue / Customer", f"${_fmt_currency(k['arpc'])}", None, None),
        ("Customer Lifetime Value", f"${_fmt_currency(ba.compute_clv(df))}", None, None),
        ("Repeat Purchase Rate", f"{ba.compute_repeat_purchase_rate(df)}%", None, None),
        ("Total Orders", f"{k['transactions']:,}", None, None),
        ("Avg Order Value", f"${_fmt_currency(k['aov'])}", None, None),
    ])

    c1, c2 = st.columns(2)
    with c1:
        section("Customer Distribution by Region")
        dist = ba.compute_customer_distribution(df)
        if not dist.empty:
            fig = px.pie(dist, names="region", values="customers", hole=0.5,
                         color_discrete_sequence=PALETTE)
            render_chart(fig, "cust_dist", height=340)
        else:
            empty_state()
    with c2:
        section("Customer Segments")
        seg = ba.compute_customer_segments(df)
        if not seg.empty:
            fig = px.bar(seg, x="segment", y="customers", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"segment": "Segment", "customers": "Customers"})
            render_chart(fig, "cust_segments", height=340, showlegend=False)
        else:
            empty_state()

    c3, c4 = st.columns(2)
    with c3:
        section("New vs Returning Customers")
        nr = ba.compute_new_vs_returning(df)
        if not nr.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=nr["period"], y=nr["new"], name="New", marker_color=ACCENT))
            fig.add_trace(go.Bar(x=nr["period"], y=nr["returning"], name="Returning", marker_color=POS))
            render_chart(fig, "cust_newret", height=340)
        else:
            empty_state()
    with c4:
        section("Order Frequency Distribution")
        freq = ba.compute_order_frequency(df)
        if not freq.empty:
            fig = px.bar(freq, x="frequency", y="customers",
                        labels={"frequency": "Orders per Customer", "customers": "Customers"})
            render_chart(fig, "cust_freq", height=340, showlegend=False)
        else:
            empty_state()

    c5, c6 = st.columns(2)
    with c5:
        section("Customer Segments")
        seg = ba.compute_customer_segments(df)
        if not seg.empty:
            fig = px.pie(seg, names="segment", values="customers", hole=0.5,
                        color_discrete_sequence=PALETTE)
            render_chart(fig, "cust_seg_pie", height=340)
        else:
            empty_state()
    with c6:
        section("Customer State Distribution")
        state_dist = df.groupby("state")["customer_id"].nunique().reset_index().sort_values("customer_id", ascending=True)
        if not state_dist.empty:
            fig = px.bar(state_dist, x="customer_id", y="state", orientation="h",
                        color="customer_id", color_continuous_scale="Blues",
                        labels={"customer_id": "Customers", "state": "State"})
            render_chart(fig, "cust_state_bar", height=340, showlegend=False)
        else:
            empty_state()

    section("Top 10 Customers")
    top = ba.compute_top_customers(df, limit=10)
    if not top.empty:
        fig = px.bar(top, x="revenue", y="customer_id", orientation="h", color="revenue",
                     color_continuous_scale="Blues",
                     labels={"revenue": "Revenue ($)", "customer_id": "Customer"})
        fig.update_layout(yaxis=dict(autorange="reversed"))
        render_chart(fig, "cust_top", height=420, showlegend=False)
    else:
        empty_state()

    section("Regional Performance")
    reg_perf = ba.compute_regional_performance(df)
    if not reg_perf.empty:
        c7, c8 = st.columns(2)
        with c7:
            fig = px.bar(reg_perf, x="region", y="revenue", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"region": "Region", "revenue": "Revenue ($)"})
            render_chart(fig, "cust_reg_rev", height=320, showlegend=False)
        with c8:
            fig = px.bar(reg_perf, x="region", y="customers", color="customers",
                        color_continuous_scale="Greens",
                        labels={"region": "Region", "customers": "Customers"})
            render_chart(fig, "cust_reg_cust", height=320, showlegend=False)
    else:
        empty_state()


# ---------------------------------------------------------------------------
# Page 4 - Product Analytics
# ---------------------------------------------------------------------------

def page_product(df: pd.DataFrame):
    section("Revenue by Product (Top 15)")
    rev_p = ba.compute_revenue_by_product(df, limit=15)
    if not rev_p.empty:
        fig = px.bar(rev_p, x="revenue", y="product_id", orientation="h", color="revenue",
                     color_continuous_scale="Blues",
                     labels={"revenue": "Revenue ($)", "product_id": "Product"})
        fig.update_layout(yaxis=dict(autorange="reversed"))
        render_chart(fig, "prod_rev", height=420, showlegend=False)
    else:
        empty_state()

    c1, c2 = st.columns(2)
    with c1:
        section("Profit by Product (Top 15)")
        prof_p = ba.compute_profit_by_product(df, limit=15)
        if not prof_p.empty:
            fig = px.bar(prof_p, x="gross_profit", y="product_id", orientation="h",
                         color="gross_profit", color_continuous_scale="Tealgrn",
                         labels={"gross_profit": "Gross Profit ($)", "product_id": "Product"})
            fig.update_layout(yaxis=dict(autorange="reversed"))
            render_chart(fig, "prod_prof", height=420, showlegend=False)
        else:
            empty_state()
    with c2:
        section("Bottom 10 Products (by Revenue)")
        bottom = ba.compute_bottom_products(df, limit=10)
        if not bottom.empty:
            fig = px.bar(bottom, x="revenue", y="product_id", orientation="h", color="revenue",
                         color_continuous_scale="Reds",
                         labels={"revenue": "Revenue ($)", "product_id": "Product"})
            fig.update_layout(yaxis=dict(autorange="reversed"))
            render_chart(fig, "prod_bottom", height=420, showlegend=False)
        else:
            empty_state()

    section("Revenue Contribution by Category")
    cat = ba.compute_revenue_by_category(df)
    if not cat.empty:
        fig = px.treemap(cat, path=["category"], values="revenue", color="revenue",
                         color_continuous_scale="Blues", labels={"revenue": "Revenue ($)"})
        render_chart(fig, "prod_treemap", height=360, showlegend=False)
    else:
        empty_state()

    c3, c4 = st.columns(2)
    with c3:
        section("Discount vs Revenue")
        d = ba.compute_discount_vs_revenue(df)
        if not d.empty:
            fig = px.scatter(d, x="discount_pct", y="revenue", color_discrete_sequence=[ACCENT],
                             labels={"discount_pct": "Discount %", "revenue": "Revenue ($)"})
            render_chart(fig, "prod_disc_rev", height=340, showlegend=False)
        else:
            empty_state()
    with c4:
        section("Discount vs Profit")
        d = ba.compute_discount_vs_profit(df)
        if not d.empty:
            fig = px.scatter(d, x="discount_pct", y="net_profit", color_discrete_sequence=[POS],
                             labels={"discount_pct": "Discount %", "net_profit": "Net Profit ($)"})
            render_chart(fig, "prod_disc_prof", height=340, showlegend=False)
        else:
            empty_state()

    c5, c6 = st.columns(2)
    with c5:
        section("Quantity vs Revenue")
        d = ba.compute_quantity_vs_revenue(df)
        if not d.empty:
            fig = px.scatter(d, x="quantity", y="revenue", color_discrete_sequence=["#0EA5E9"],
                             labels={"quantity": "Quantity", "revenue": "Revenue ($)"})
            render_chart(fig, "prod_qty_rev", height=340, showlegend=False)
        else:
            empty_state()
    with c6:
        section("Revenue Distribution")
        d = ba.compute_revenue_distribution(df)
        if not d.empty:
            fig = px.bar(d, x="bucket", y="count", color_discrete_sequence=[ACCENT],
                         labels={"bucket": "Revenue ($)", "count": "Order Lines"})
            render_chart(fig, "prod_rev_dist", height=340, showlegend=False)
        else:
            empty_state()

    section("Category Margin Analysis")
    cat_margin = ba.compute_category_margin(df)
    if not cat_margin.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=cat_margin["category"], y=cat_margin["gross_margin"], name="Gross Margin %", marker_color=ACCENT))
        fig.add_trace(go.Bar(x=cat_margin["category"], y=cat_margin["net_margin"], name="Net Margin %", marker_color=POS))
        render_chart(fig, "prod_cat_margin", height=360)
    else:
        empty_state()

    section("Top 10 Deals")
    top_deals = ba.compute_top_deals(df, limit=10)
    if not top_deals.empty:
        fig = px.bar(top_deals, x="revenue", y="order_id", orientation="h", color="revenue",
                     color_continuous_scale="Blues",
                     labels={"revenue": "Revenue ($)", "order_id": "Order"})
        fig.update_layout(yaxis=dict(autorange="reversed"))
        render_chart(fig, "prod_top_deals", height=400, showlegend=False)
    else:
        empty_state()


# ---------------------------------------------------------------------------
# Page 5 - Geographic Analytics
# ---------------------------------------------------------------------------

def page_geo(df: pd.DataFrame):
    section("Sales by Region")
    reg = ba.compute_sales_by_region(df)
    if not reg.empty:
        fig = px.scatter_geo(reg, lat="lat", lon="lon", size="revenue", color="region",
                             scope="asia", hover_name="region",
                             hover_data={"revenue": ":.0f", "lat": False, "lon": False},
                             labels={"revenue": "Revenue ($)"})
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
        render_chart(fig, "geo_region", height=460)
    else:
        empty_state()

    section("Revenue by State")
    stt = ba.compute_revenue_by_state(df)
    if not stt.empty:
        fig = px.bar(stt, x="state", y="revenue", color="revenue", color_continuous_scale="Blues",
                     labels={"state": "State", "revenue": "Revenue ($)"})
        render_chart(fig, "geo_state", height=360, showlegend=False)
    else:
        empty_state()

    section("Customer Concentration by Region")
    dist = ba.compute_customer_distribution(df)
    if not dist.empty:
        fig = px.bar(dist, x="region", y="customers", color="customers", color_continuous_scale="Blues",
                     labels={"region": "Region", "customers": "Customers"})
        render_chart(fig, "geo_cust", height=340, showlegend=False)
    else:
        empty_state()

    section("Regional Performance Deep Dive")
    reg_perf = ba.compute_regional_performance(df)
    if not reg_perf.empty:
        c1, c2, c3 = st.columns(3)
        with c1:
            fig = px.bar(reg_perf, x="region", y="revenue", color="region",
                        labels={"region": "Region", "revenue": "Revenue ($)"})
            render_chart(fig, "geo_reg_rev", height=300, showlegend=False)
        with c2:
            fig = px.bar(reg_perf, x="region", y="orders", color="region",
                        labels={"region": "Region", "orders": "Orders"})
            render_chart(fig, "geo_reg_ord", height=300, showlegend=False)
        with c3:
            fig = px.bar(reg_perf, x="region", y="customers", color="region",
                        labels={"region": "Region", "customers": "Customers"})
            render_chart(fig, "geo_reg_cust", height=300, showlegend=False)
    else:
        empty_state()

    section("Regional Margin Analysis")
    reg_margin = df.groupby("region").agg(
        gross_profit=("gross_profit", "sum"),
        net_profit=("net_profit", "sum"),
        revenue=("revenue", "sum"),
    ).reset_index()
    if not reg_margin.empty:
        reg_margin["gross_margin"] = (reg_margin["gross_profit"] / reg_margin["revenue"] * 100).round(1)
        reg_margin["net_margin"] = (reg_margin["net_profit"] / reg_margin["revenue"] * 100).round(1)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=reg_margin["region"], y=reg_margin["gross_margin"], name="Gross Margin %", marker_color=ACCENT))
        fig.add_trace(go.Bar(x=reg_margin["region"], y=reg_margin["net_margin"], name="Net Margin %", marker_color=POS))
        render_chart(fig, "geo_reg_margin", height=360)
    else:
        empty_state()


# ---------------------------------------------------------------------------
# Page 6 - Profitability & Performance
# ---------------------------------------------------------------------------

def page_profit(df: pd.DataFrame, k: dict):
    kpi_row([
        ("Gross Profit", f"${_fmt_currency(k['gross_profit'])}", None, None),
        ("Net Profit", f"${_fmt_currency(k['net_profit'])}", k["profit_growth"], True),
        ("Gross Margin %", f"{k['gross_margin']}%", None, None),
        ("Net Margin %", f"{k['net_margin']}%", None, None),
        ("Total Cost", f"${_fmt_currency(ba.compute_advanced_kpis(df)['total_cost'])}", None, None),
        ("Avg Discount", f"{ba.compute_advanced_kpis(df)['avg_disc']}%", None, None),
    ])

    section("Profit vs Target")
    pvt = ba.compute_profit_vs_target(df)
    if not pvt.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=pvt["period"], y=pvt["net_profit"], name="Actual", marker_color=POS))
        fig.add_trace(go.Scatter(x=pvt["period"], y=pvt["target"], name="Target",
                                 mode="lines+markers", line=dict(color=ACCENT, dash="dash")))
        render_chart(fig, "prof_target", height=360)
    else:
        empty_state()

    section("Channel Profitability")
    chan = ba.compute_channel_profitability(df)
    if not chan.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=chan["channel"], y=chan["revenue"], name="Revenue", marker_color=ACCENT))
        fig.add_trace(go.Bar(x=chan["channel"], y=chan["gross_profit"], name="Gross Profit", marker_color=POS))
        fig.add_trace(go.Bar(x=chan["channel"], y=chan["net_profit"], name="Net Profit", marker_color="#0EA5E9"))
        render_chart(fig, "prof_channel", height=360)
    else:
        empty_state()

    section("Category Margin Analysis")
    cat_margin = ba.compute_category_margin(df)
    if not cat_margin.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=cat_margin["category"], y=cat_margin["gross_margin"], name="Gross Margin %", marker_color=ACCENT))
        fig.add_trace(go.Bar(x=cat_margin["category"], y=cat_margin["net_margin"], name="Net Margin %", marker_color=POS))
        render_chart(fig, "prof_cat_margin", height=360)
    else:
        empty_state()

    section("Channel Margin Analysis")
    chan_margin = ba.compute_channel_margin(df)
    if not chan_margin.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=chan_margin["channel"], y=chan_margin["gross_margin"], name="Gross Margin %", marker_color=ACCENT))
        fig.add_trace(go.Bar(x=chan_margin["channel"], y=chan_margin["net_margin"], name="Net Margin %", marker_color=POS))
        render_chart(fig, "prof_chan_margin", height=360)
    else:
        empty_state()

    section("KPI Performance Heatmap (Category x Month Revenue)")
    heat = ba.compute_kpi_heatmap(df)
    if not heat.empty:
        fig = px.imshow(heat, color_continuous_scale="Blues", aspect="auto",
                        labels={"x": "Month", "y": "Category", "color": "Revenue ($)"})
        render_chart(fig, "prof_heatmap", height=420, showlegend=False)
    else:
        empty_state()

    section("Month-over-Month Profit Growth")
    mom = ba.compute_mom_growth(df)
    if not mom.empty:
        fig = px.bar(mom, x="period", y="growth_pct",
                    labels={"period": "Month", "growth_pct": "Growth %"})
        render_chart(fig, "prof_mom", height=320, showlegend=False)
    else:
        empty_state()

    section("Category Revenue Distribution")
    cat = ba.compute_revenue_by_category(df)
    if not cat.empty:
        fig = px.treemap(cat, path=["category"], values="revenue",
                         color="revenue", color_continuous_scale="Blues",
                         labels={"revenue": "Revenue ($)"})
        render_chart(fig, "prof_cat_treemap", height=400, showlegend=False)
    else:
        empty_state()

    section("Executive Performance Score")
    score = ba.compute_executive_score(df)
    gauge_color = POS if score >= 70 else (ACCENT if score >= 50 else NEG)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, number={"suffix": " / 100", "font": {"color": NAVY}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": MUTED},
            "bar": {"color": gauge_color}, "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [
                {"range": [0, 50], "color": "rgba(220,38,38,0.18)"},
                {"range": [50, 70], "color": "rgba(31,111,235,0.18)"},
                {"range": [70, 100], "color": "rgba(22,163,74,0.18)"},
            ],
        },
    ))
    render_chart(fig, "prof_score", height=320, showlegend=False)


# ---------------------------------------------------------------------------
# Page 7 - Advanced Analytics (41-60)
# ---------------------------------------------------------------------------

def page_advanced(df: pd.DataFrame):
    ak = ba.compute_advanced_kpis(df)
    kpi_row([
        ("Total Orders", f"{ak['total_orders']:,}", None, None),
        ("Avg Quantity / Order", f"{ak['avg_qty']:.1f}", None, None),
        ("Avg Discount %", f"{ak['avg_disc']:.1f}%", None, None),
        ("Total Cost", f"${_fmt_currency(ak['total_cost'])}", None, None),
        ("Repeat Purchase Rate", f"{ak['repeat_rate']:.1f}%", None, None),
        ("Customer Lifetime Value", f"${_fmt_currency(ak['clv'])}", None, None),
    ], ncols=6)

    # 41-45: Distributions
    section("Revenue & Value Distributions")
    c1, c2, c3 = st.columns(3)
    with c1:
        section("41. Revenue Distribution")
        d = ba.compute_revenue_distribution(df)
        if not d.empty:
            fig = px.histogram(d, x="bucket", y="count", nbins=20,
                              labels={"bucket": "Revenue ($)", "count": "Frequency"})
            render_chart(fig, "adv_rev_dist", height=300, showlegend=False)
        else:
            empty_state()
    with c2:
        section("42. Order Value Distribution")
        d = ba.compute_revenue_distribution(df)
        if not d.empty:
            fig = px.histogram(d, x="bucket", y="count", nbins=20,
                              labels={"bucket": "Order Value ($)", "count": "Frequency"})
            render_chart(fig, "adv_order_dist", height=300, showlegend=False)
        else:
            empty_state()
    with c3:
        section("43. Customer Spend Distribution")
        d = ba.compute_customer_spend_distribution(df)
        if not d.empty:
            fig = px.histogram(d, x="bucket", y="count", nbins=20,
                              labels={"bucket": "Customer Spend ($)", "count": "Customers"})
            render_chart(fig, "adv_cust_spend", height=300, showlegend=False)
        else:
            empty_state()

    c4, c5 = st.columns(2)
    with c4:
        section("44. Product Price Distribution")
        d = ba.compute_price_distribution(df)
        if not d.empty:
            fig = px.histogram(d, x="bucket", y="count", nbins=20,
                              labels={"bucket": "Unit Price ($)", "count": "Products"})
            render_chart(fig, "adv_price_dist", height=300, showlegend=False)
        else:
            empty_state()
    with c5:
        section("45. Profit Margin Distribution")
        d = ba.compute_margin_distribution(df)
        if not d.empty:
            fig = px.histogram(d, x="bucket", y="count", nbins=20,
                              labels={"bucket": "Margin %", "count": "Order Lines"})
            render_chart(fig, "adv_margin_dist", height=300, showlegend=False)
        else:
            empty_state()

    # 46-48: Temporal Patterns
    section("Temporal Patterns")
    c6, c7, c8 = st.columns(3)
    with c6:
        section("46. Sales Frequency by Day")
        d = ba.compute_sales_by_day(df)
        if not d.empty:
            fig = px.histogram(d, x="day", y="orders", nbins=31,
                              labels={"day": "Day of Month", "orders": "Transactions"})
            render_chart(fig, "adv_sales_day", height=300, showlegend=False)
        else:
            empty_state()
    with c7:
        section("47. Sales by Day of Week")
        d = ba.compute_sales_by_dow(df)
        if not d.empty:
            fig = px.bar(d, x="weekday", y="revenue", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"weekday": "Day", "revenue": "Revenue ($)"})
            render_chart(fig, "adv_sales_dow", height=300, showlegend=False)
        else:
            empty_state()
    with c8:
        section("48. Sales by Hour")
        d = ba.compute_sales_by_hour(df)
        if not d.empty:
            fig = px.area(d, x="hour", y="revenue",
                         labels={"hour": "Hour of Day", "revenue": "Revenue ($)"})
            render_chart(fig, "adv_sales_hour", height=300, showlegend=False)
        else:
            empty_state()

    # 49-53: Scatter Plots
    section("Relationship Analysis")
    c9, c10, c11 = st.columns(3)
    with c9:
        section("49. Revenue vs Profit")
        d = ba.compute_revenue_vs_profit(df)
        if not d.empty:
            fig = px.scatter(d, x="revenue", y="net_profit",
                            labels={"revenue": "Revenue ($)", "net_profit": "Net Profit ($)"})
            render_chart(fig, "adv_rev_prof", height=300, showlegend=False)
        else:
            empty_state()
    with c10:
        section("50. Orders vs Revenue")
        d = ba.compute_quantity_vs_revenue(df)
        if not d.empty:
            fig = px.scatter(d, x="quantity", y="revenue",
                            labels={"quantity": "Order Lines", "revenue": "Revenue ($)"})
            render_chart(fig, "adv_ord_rev", height=300, showlegend=False)
        else:
            empty_state()
    with c11:
        section("51. Customers vs Revenue")
        d = ba.compute_customers_vs_revenue(df)
        if not d.empty:
            fig = px.scatter(d, x="orders", y="revenue",
                            labels={"orders": "Orders per Customer", "revenue": "Revenue ($)"})
            render_chart(fig, "adv_cust_rev", height=300, showlegend=False)
        else:
            empty_state()

    c12, c13 = st.columns(2)
    with c12:
        section("52. Price vs Quantity Sold")
        d = ba.compute_price_vs_quantity(df)
        if not d.empty:
            fig = px.scatter(d, x="unit_price", y="quantity",
                            labels={"unit_price": "Unit Price ($)", "quantity": "Quantity"})
            render_chart(fig, "adv_price_qty", height=300, showlegend=False)
        else:
            empty_state()
    with c13:
        section("53. Discount vs Quantity")
        d = ba.compute_discount_vs_quantity(df)
        if not d.empty:
            fig = px.scatter(d, x="discount_pct", y="quantity",
                            labels={"discount_pct": "Discount %", "quantity": "Quantity"})
            render_chart(fig, "adv_disc_qty", height=300, showlegend=False)
        else:
            empty_state()

    # 54-56: Heatmaps & Matrices
    section("Correlation & Cohort Analysis")
    c14, c15 = st.columns(2)
    with c14:
        section("54. Correlation Matrix")
        corr = ba.compute_correlation_matrix(df)
        if not corr.empty:
            fig = px.imshow(corr, text_auto=True, aspect="auto",
                           color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                           labels={"color": "Correlation"})
            render_chart(fig, "adv_corr", height=420, showlegend=False)
        else:
            empty_state()
    with c15:
        section("55. Monthly Performance Heatmap")
        heat = ba.compute_kpi_heatmap(df)
        if not heat.empty:
            fig = px.imshow(heat, text_auto=True, aspect="auto",
                           color_continuous_scale="Blues",
                           labels={"x": "Month", "y": "Category", "color": "Revenue ($)"})
            render_chart(fig, "adv_heat", height=420, showlegend=False)
        else:
            empty_state()

    section("56. Cohort Retention Matrix")
    cohort = ba.compute_cohort_retention(df)
    if not cohort.empty:
        fig = px.imshow(cohort, text_auto=True, aspect="auto",
                       color_continuous_scale="Greens",
                       labels={"x": "Order Month", "y": "Acquisition Cohort", "color": "Customers"})
        render_chart(fig, "adv_cohort", height=500, showlegend=False)
    else:
        empty_state()

    # 57-60: Waterfall, Funnel, Pareto
    section("Performance Drivers")
    c16, c17 = st.columns(2)
    with c16:
        section("57. Revenue Waterfall")
        wf = ba.compute_revenue_waterfall(df)
        if not wf.empty:
            fig = go.Figure(go.Waterfall(
                x=wf["period"], y=wf["change"],
                text=wf["change"].round(0),
                connector={"line": {"color": MUTED}},
                increasing={"marker": {"color": POS}},
                decreasing={"marker": {"color": NEG}},
            ))
            render_chart(fig, "adv_rev_wf", height=360, showlegend=False)
        else:
            empty_state()
    with c17:
        section("58. Profit Waterfall")
        wf = ba.compute_profit_waterfall(df)
        if not wf.empty:
            fig = go.Figure(go.Waterfall(
                x=wf["period"], y=wf["change"],
                text=wf["change"].round(0),
                connector={"line": {"color": MUTED}},
                increasing={"marker": {"color": POS}},
                decreasing={"marker": {"color": NEG}},
            ))
            render_chart(fig, "adv_prof_wf", height=360, showlegend=False)
        else:
            empty_state()

    c18, c19 = st.columns(2)
    with c18:
        section("59. Sales Funnel")
        funnel = ba.compute_sales_funnel(df)
        if not funnel.empty:
            fig = go.Figure(go.Funnel(
                y=funnel["stage"], x=funnel["value"],
                textinfo="value+percent initial",
                marker={"color": [ACCENT, POS, MUTED, NAVY]},
            ))
            render_chart(fig, "adv_funnel", height=360, showlegend=False)
        else:
            empty_state()
    with c19:
        section("60. Pareto Analysis")
        pareto = ba.compute_pareto(df)
        if not pareto.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=pareto["product_id"], y=pareto["revenue"],
                name="Revenue", marker_color=ACCENT,
            ))
            fig.add_trace(go.Scatter(
                x=pareto["product_id"], y=pareto["cumulative_pct"],
                name="Cumulative %", mode="lines+markers",
                line=dict(color=NEG), yaxis="y2",
            ))
            fig.update_layout(
                yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 100]),
            )
            render_chart(fig, "adv_pareto", height=420)
        else:
            empty_state()


# ---------------------------------------------------------------------------
# Page 8 - Real-time Monitor
# ---------------------------------------------------------------------------


def page_realtime(df: pd.DataFrame, k: dict):
    rt = ba.compute_realtime_metrics(df)
    kpi_row([
        ("Orders (Last Min)", f"{rt['orders_last_min']:,}", None, None),
        ("Revenue (Last Min)", f"${_fmt_currency(rt['revenue_last_min'])}", None, None),
        ("Active Customers", f"{rt['active_customers']:,}", None, None),
        ("Total Orders", f"{k['transactions']:,}", None, None),
        ("Total Revenue", f"${_fmt_currency(k['revenue'])}", None, None),
        ("Avg Order Value", f"${_fmt_currency(k['aov'])}", None, None),
    ], ncols=6)

    section("Basket Size Distribution")
    basket = ba.compute_basket_size(df)
    if not basket.empty:
        fig = px.bar(basket, x="basket_size", y="orders",
                    labels={"basket_size": "Items per Order", "orders": "Orders"})
        render_chart(fig, "rt_basket", height=340, showlegend=False)
    else:
        empty_state()

    section("Daily Revenue & Order Trends")
    daily = ba.compute_daily_trends(df)
    if not daily.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.line(daily, x="date", y="revenue", markers=True,
                         labels={"date": "Date", "revenue": "Revenue ($)"})
            render_chart(fig, "rt_daily_rev", height=320)
        with c2:
            fig = px.line(daily, x="date", y="orders", markers=True,
                         labels={"date": "Date", "orders": "Orders"})
            render_chart(fig, "rt_daily_ord", height=320)
    else:
        empty_state()

    section("Weekly Revenue & Order Trends")
    weekly = ba.compute_weekly_trends(df)
    if not weekly.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(weekly, x="week", y="revenue", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"week": "Week", "revenue": "Revenue ($)"})
            render_chart(fig, "rt_weekly_rev", height=320, showlegend=False)
        with c2:
            fig = px.bar(weekly, x="week", y="orders", color="orders",
                        color_continuous_scale="Greens",
                        labels={"week": "Week", "orders": "Orders"})
            render_chart(fig, "rt_weekly_ord", height=320, showlegend=False)
    else:
        empty_state()

    section("Latest Orders")
    latest = df.sort_values("order_date", ascending=False).head(50)
    if not latest.empty:
        st.dataframe(
            latest[["order_id", "order_date", "customer_id", "category", "channel", "quantity", "revenue", "discount_pct"]],
            use_container_width=True,
            height=400,
        )
    else:
        empty_state()

    section("Channel Performance")
    chan_perf = ba.compute_channel_share(df)
    if not chan_perf.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.pie(chan_perf, names="channel", values="revenue", hole=0.5,
                        color_discrete_sequence=PALETTE)
            render_chart(fig, "rt_chan_pie", height=340)
        with c2:
            fig = px.bar(chan_perf, x="channel", y="revenue", color="revenue",
                        color_continuous_scale="Blues",
                        labels={"channel": "Channel", "revenue": "Revenue ($)"})
            render_chart(fig, "rt_chan_bar", height=340, showlegend=False)
    else:
        empty_state()

    section("Category Performance")
    cat_perf = ba.compute_category_share(df)
    if not cat_perf.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.pie(cat_perf, names="category", values="revenue", hole=0.5,
                        color_discrete_sequence=PALETTE)
            render_chart(fig, "rt_cat_pie", height=340)
        with c2:
            fig = px.bar(cat_perf, x="category", y="revenue", color="revenue",
                        color_continuous_scale="Tealgrn",
                        labels={"category": "Category", "revenue": "Revenue ($)"})
            render_chart(fig, "rt_cat_bar", height=340, showlegend=False)
    else:
        empty_state()

    section("Discount Impact Analysis")
    disc_impact = ba.compute_discount_impact(df)
    if not disc_impact.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(disc_impact, x="discount_bucket", y="revenue",
                        labels={"discount_bucket": "Discount %", "revenue": "Revenue ($)"})
            render_chart(fig, "rt_disc_rev", height=320, showlegend=False)
        with c2:
            fig = px.line(disc_impact, x="discount_bucket", y="orders", markers=True,
                         labels={"discount_bucket": "Discount %", "orders": "Orders"})
            render_chart(fig, "rt_disc_ord", height=320)
    else:
        empty_state()

    section("Basket Size Distribution")
    basket = ba.compute_basket_size(df)
    if not basket.empty:
        fig = px.bar(basket, x="basket_size", y="orders",
                    labels={"basket_size": "Items per Order", "orders": "Orders"})
        render_chart(fig, "rt_basket", height=320, showlegend=False)
    else:
        empty_state()

    section("Order Frequency Distribution")
    freq = ba.compute_order_frequency(df)
    if not freq.empty:
        fig = px.bar(freq, x="frequency", y="customers",
                    labels={"frequency": "Orders per Customer", "customers": "Customers"})
        render_chart(fig, "rt_freq", height=320, showlegend=False)
    else:
        empty_state()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@st.fragment(run_every=20)
def render_business_dashboard():
    st.markdown(BD_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="bd-hero">'
        '<div class="bd-title">FrostPulse — Business Analytics</div>'
        '<div class="bd-sub">Executive sales, customer, product and profitability intelligence</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    filters = render_filters()
    df = ba.load_orders(filters)
    k = ba.compute_kpis(df)

    if df.empty:
        st.warning("No data matches the selected filters. Adjust the filters above.")
        st.markdown('<div class="bd-footer">Made by Sourish Dey</div>', unsafe_allow_html=True)
        return

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Export filtered data (CSV)", data=csv,
        file_name="frostpulse_business_export.csv", mime="text/csv",
    )

    tabs = st.tabs([
        "Executive Overview", "Sales Analytics", "Customer Analytics",
        "Product Analytics", "Geographic Analytics", "Profitability & Performance",
        "Advanced Analytics", "Real-time Monitor",
    ])
    with tabs[0]:
        page_executive(df, k)
    with tabs[1]:
        page_sales(df)
    with tabs[2]:
        page_customer(df, k)
    with tabs[3]:
        page_product(df)
    with tabs[4]:
        page_geo(df)
    with tabs[5]:
        page_profit(df, k)
    with tabs[6]:
        page_advanced(df)
    with tabs[7]:
        page_realtime(df, k)

    st.markdown('<div class="bd-footer">Made by Sourish Dey</div>', unsafe_allow_html=True)
