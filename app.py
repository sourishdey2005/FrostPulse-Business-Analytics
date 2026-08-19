"""
app.py

FrostPulse - Cold-Chain Intelligence and Shipment Risk Monitoring.

Responsible only for Streamlit UI: dashboard layout, KPI cards, charts,
and orchestration of data generation / pipeline calls. All SQL lives in
analytics.py, schema in database.py, synthetic data in generator.py,
and ETL logic in pipeline.py.
"""

from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analytics
import business_dashboard
from business_generator import seed_business_data
from database import initialize_database, table_row_count
from generator import generate_batch, generate_historical_batch
from pipeline import run_pipeline, seed_master_data

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FrostPulse",
    page_icon="assets/favicon.ico" if False else None,
    layout="wide",
)

NAVY = "#0A1F33"
ICE_BLUE = "#1F6FEB"
CYAN = "#22D3EE"
WHITE = "#F5F7FA"
LIGHT_GRAY = "#B8C2CC"
SAFE_COLOR = "#2ECC71"
WARNING_COLOR = "#F39C12"
HIGH_COLOR = "#E67E22"
CRITICAL_COLOR = "#C0392B"

STATUS_COLOR_MAP = {"SAFE": SAFE_COLOR, "WARNING": WARNING_COLOR, "CRITICAL": CRITICAL_COLOR}
RISK_COLOR_MAP = {"LOW": SAFE_COLOR, "MEDIUM": WARNING_COLOR, "HIGH": HIGH_COLOR, "CRITICAL": CRITICAL_COLOR}

REFRESH_SECONDS = 20
RECORDS_PER_CYCLE = (20, 50)

CUSTOM_CSS = f"""
<style>
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    .block-container {{ padding-top: 1.5rem; padding-bottom: 1.5rem; max-width: 1400px; }}

    .fp-title {{
        font-size: 2.4rem;
        font-weight: 700;
        color: {WHITE};
        margin-bottom: 0;
    }}
    .fp-subtitle {{
        font-size: 1.0rem;
        color: {LIGHT_GRAY};
        margin-top: 0;
        letter-spacing: 0.02em;
    }}
    .fp-status-row {{
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin: 0.4rem 0 1.2rem 0;
        font-size: 0.9rem;
        color: {LIGHT_GRAY};
    }}
    .fp-live-dot {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background-color: {SAFE_COLOR};
        display: inline-block;
    }}
    .fp-section-header {{
        font-size: 1.15rem;
        font-weight: 600;
        color: {WHITE};
        border-left: 4px solid {CYAN};
        padding-left: 0.6rem;
        margin: 1.6rem 0 0.8rem 0;
    }}
    div[data-testid="stMetric"] {{
        background-color: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 0.8rem 0.9rem 0.6rem 0.9rem;
    }}
    div[data-testid="stMetricLabel"] {{
        color: {LIGHT_GRAY};
    }}
    .fp-footer {{
        text-align: center;
        color: {LIGHT_GRAY};
        font-size: 0.85rem;
        margin-top: 2.5rem;
        padding-top: 1rem;
        border-top: 1px solid rgba(255,255,255,0.08);
    }}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def _theme(fig, height: int = 360, showlegend: bool = True, margin=None):
    """Apply the FrostPulse dark theme consistently to a Plotly figure."""
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=margin or dict(l=10, r=10, t=10, b=10),
        showlegend=showlegend,
        legend_title_text="",
        font=dict(color=LIGHT_GRAY),
    )
    return fig

# ---------------------------------------------------------------------------
# Startup: initialize database and seed data (runs once per session/process)
# ---------------------------------------------------------------------------


@st.cache_resource
def bootstrap() -> bool:
    is_new = initialize_database()
    seed_master_data()
    if is_new or table_row_count("fact_sensor_reading") == 0:
        historical = generate_historical_batch(count=700, span_minutes=45)
        run_pipeline(historical)
    # Seed the independent Business Analytics layer (synthetic sales data).
    seed_business_data(months=24)
    return True


bootstrap()

# ---------------------------------------------------------------------------
# Navigation and view rendering are defined at the end of the script.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Auto-refreshing dashboard fragment
# ---------------------------------------------------------------------------

@st.fragment(run_every=REFRESH_SECONDS)
def live_dashboard():
    import random

    # --- incremental data generation + pipeline run -------------------------
    batch_size = random.randint(*RECORDS_PER_CYCLE)
    try:
        new_events = generate_batch(batch_size)
        run_pipeline(new_events)
        pipeline_error = None
    except Exception as exc:  # noqa: BLE001
        pipeline_error = str(exc)

    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    st.markdown(
        f'<div class="fp-status-row"><span class="fp-live-dot"></span>'
        f'LIVE SYSTEM &nbsp;|&nbsp; Last updated: {now_str}</div>',
        unsafe_allow_html=True,
    )
    if pipeline_error:
        st.warning("Pipeline encountered an issue processing the latest batch. Retrying next cycle.")

    top = analytics.get_top_kpis()
    second = analytics.get_second_kpis()
    pipeline_health = analytics.get_pipeline_health()
    freshness = analytics.get_data_freshness_seconds()
    anomaly_rate = analytics.get_anomaly_rate()

    # ---------------------------------------------------------------- KPI 1
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Shipments", f"{top['total_shipments']}")
    c2.metric("Active Vehicles", f"{top['active_vehicles']}")
    c3.metric("Total Sensor Readings", f"{top['total_readings']:,}")
    c4.metric("At-Risk Shipments", f"{top['at_risk_shipments']}")
    c5.metric("Temperature Compliance", f"{top['temperature_compliance']}%")
    c6.metric("Average Risk Score", f"{top['avg_risk_score']}")

    # ---------------------------------------------------------------- KPI 2
    d1, d2, d3, d4, d5, d6 = st.columns(6)
    d1.metric("Critical Incidents", f"{second['critical_incidents']}")
    d2.metric("Warning Incidents", f"{second['warning_incidents']}")
    d3.metric("Average Temperature", f"{second['avg_temperature']} C")
    d4.metric("Average Humidity", f"{second['avg_humidity']}%")
    d5.metric("Low Battery Vehicles", f"{second['low_battery_vehicles']}")
    d6.metric("Data Quality Score", f"{second['data_quality_score']}%")

    # ---------------------------------------------------------- KPI 3 (extra)
    st.markdown('<div class="fp-section-header">Extended Operational Metrics</div>', unsafe_allow_html=True)
    e1, e2, e3, e4, e5, e6 = st.columns(6)
    dq_df = analytics.get_data_quality_summary()
    dq_pass = int((dq_df["status"] == "PASS").sum()) if not dq_df.empty else 0
    dq_total = len(dq_df) if not dq_df.empty else 0
    rejection_df = analytics.get_rejection_reasons()
    total_rejections = int(rejection_df["count"].sum()) if not rejection_df.empty else 0
    incident_type_df = analytics.get_incident_type_counts()
    top_incident_type = incident_type_df.iloc[0]["incident_type"] if not incident_type_df.empty else "None"
    delivery_df = analytics.get_delivery_status_counts()
    in_transit = int(delivery_df.loc[delivery_df["delivery_status"] == "IN_TRANSIT", "count"].sum()) \
        if not delivery_df.empty else 0
    warehouse_df = analytics.get_status_by_warehouse()
    riskiest_warehouse = warehouse_df.iloc[0]["warehouse"] if not warehouse_df.empty else "N/A"

    e1.metric("Anomaly Rate", f"{anomaly_rate}%")
    e2.metric("Data Quality Checks Passed", f"{dq_pass}/{dq_total}" if dq_total else "N/A")
    e3.metric("Total Rejected Records", f"{total_rejections}")
    e4.metric("Top Incident Type", top_incident_type)
    e5.metric("Shipments In Transit", f"{in_transit}")
    e6.metric("Highest-Risk Warehouse", riskiest_warehouse)

    f1, f2, f3, f4, f5, f6 = st.columns(6)
    vehicle_health_df = analytics.get_vehicle_health()
    riskiest_vehicle = vehicle_health_df.iloc[0]["vehicle_id"] if not vehicle_health_df.empty else "N/A"
    avg_battery_all = vehicle_health_df["avg_battery"].mean() if not vehicle_health_df.empty else 0.0
    shipment_health_df = analytics.get_shipment_health()
    healthy_shipments = int((shipment_health_df["status"] == "HEALTHY").sum()) if not shipment_health_df.empty else 0
    at_risk_shipments_h = int((shipment_health_df["status"] == "AT RISK").sum()) if not shipment_health_df.empty else 0
    avg_health_score = round(shipment_health_df["health_score"].mean(), 1) if not shipment_health_df.empty else 0.0
    incident_severity_df = analytics.get_incident_severity_counts()
    total_incidents = int(incident_severity_df["count"].sum()) if not incident_severity_df.empty else 0

    f1.metric("Riskiest Vehicle", riskiest_vehicle)
    f2.metric("Fleet Avg Battery", f"{round(avg_battery_all, 1)}%")
    f3.metric("Healthy Shipments", f"{healthy_shipments}")
    f4.metric("At-Risk (Health) Shipments", f"{at_risk_shipments_h}")
    f5.metric("Avg Shipment Health Score", f"{avg_health_score}")
    f6.metric("Total Incidents Logged", f"{total_incidents}")

    # ------------------------------------------------------------- Charts 1
    st.markdown('<div class="fp-section-header">Live Temperature Monitoring</div>', unsafe_allow_html=True)
    temp_df = analytics.get_recent_temperature_readings(limit=150)
    if not temp_df.empty:
        temp_df["event_timestamp"] = pd.to_datetime(temp_df["event_timestamp"])
        fig = px.line(
            temp_df, x="event_timestamp", y="temperature_c", color="temperature_status",
            color_discrete_map=STATUS_COLOR_MAP, markers=False,
            labels={"event_timestamp": "Time", "temperature_c": "Temperature (C)", "temperature_status": "Status"},
        )
        fig.update_layout(
            template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            height=380, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="",
        )
        st.plotly_chart(fig, use_container_width=True, key="temp_chart")
    else:
        st.info("Waiting for sensor data.")

    # ------------------------------------------------------------- Charts 2
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown('<div class="fp-section-header">Temperature Compliance</div>', unsafe_allow_html=True)
        comp_df = analytics.get_temperature_compliance_distribution()
        if not comp_df.empty:
            total_readings = comp_df["count"].sum()
            fig = go.Figure(data=[go.Pie(
                labels=comp_df["status"], values=comp_df["count"], hole=0.6,
                marker=dict(colors=[STATUS_COLOR_MAP.get(s, LIGHT_GRAY) for s in comp_df["status"]]),
            )])
            safe_pct = round(comp_df.loc[comp_df["status"] == "SAFE", "count"].sum() / total_readings * 100, 1) \
                if total_readings else 0.0
            fig.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=340,
                margin=dict(l=10, r=10, t=10, b=10),
                annotations=[dict(text=f"{safe_pct}%<br>SAFE", showarrow=False, font_size=16)],
            )
            st.plotly_chart(fig, use_container_width=True, key="compliance_donut")
    with col_b:
        st.markdown('<div class="fp-section-header">Shipment Risk Distribution</div>', unsafe_allow_html=True)
        risk_df = analytics.get_risk_distribution()
        if not risk_df.empty:
            order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
            risk_df["risk_level"] = pd.Categorical(risk_df["risk_level"], categories=order, ordered=True)
            risk_df = risk_df.sort_values("risk_level")
            fig = px.bar(
                risk_df, x="risk_level", y="count", color="risk_level",
                color_discrete_map=RISK_COLOR_MAP,
                labels={"risk_level": "Risk Level", "count": "Shipments"},
            )
            fig.update_layout(
                template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                height=340, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True, key="risk_bar")

    # ------------------------------------------------------------- Charts 3
    col_c, col_d = st.columns(2)
    with col_c:
        st.markdown('<div class="fp-section-header">Risk by Food Category</div>', unsafe_allow_html=True)
        food_df = analytics.get_risk_by_food_category()
        if not food_df.empty:
            fig = px.bar(
                food_df, x="food_category", y="avg_risk", color="avg_risk",
                color_continuous_scale=["#2ECC71", "#F39C12", "#C0392B"],
                labels={"food_category": "Food Category", "avg_risk": "Avg Risk Score"},
            )
            fig.update_layout(
                template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                height=340, margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True, key="food_risk_bar")
    with col_d:
        st.markdown('<div class="fp-section-header">Vehicle Health</div>', unsafe_allow_html=True)
        if not vehicle_health_df.empty:
            vdf = vehicle_health_df.sort_values("avg_risk", ascending=True)
            fig = px.bar(
                vdf, x="avg_risk", y="vehicle_id", orientation="h", color="avg_risk",
                color_continuous_scale=["#2ECC71", "#F39C12", "#C0392B"],
                labels={"avg_risk": "Avg Risk Score", "vehicle_id": "Vehicle"},
            )
            fig.update_layout(
                template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                height=340, margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True, key="vehicle_health_bar")

    # --------------------------------------------------- Supply-chain risk flow
    st.markdown(
        '<div class="fp-section-header">Supply-Chain Risk Flow '
        '(Warehouse &rarr; Category &rarr; Risk)</div>',
        unsafe_allow_html=True,
    )
    flow_df = analytics.get_warehouse_food_risk_flow()
    if not flow_df.empty:
        warehouses = flow_df["warehouse"].unique().tolist()
        categories = flow_df["food_category"].unique().tolist()
        risk_levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        w_idx = {w: i for i, w in enumerate(warehouses)}
        c_idx = {c: len(warehouses) + i for i, c in enumerate(categories)}
        r_idx = {r: len(warehouses) + len(categories) + i for i, r in enumerate(risk_levels)}

        nodes = warehouses + categories + risk_levels
        node_colors = (
            ["#1F6FEB"] * len(warehouses)
            + ["#22D3EE"] * len(categories)
            + [RISK_COLOR_MAP[r] for r in risk_levels]
        )

        src, tgt, val = [], [], []
        for _, row in flow_df.iterrows():
            src.append(w_idx[row["warehouse"]])
            tgt.append(c_idx[row["food_category"]])
            val.append(int(row["count"]))
        for _, row in flow_df.iterrows():
            src.append(c_idx[row["food_category"]])
            tgt.append(r_idx[row["risk_level"]])
            val.append(int(row["count"]))

        fig = go.Figure(go.Sankey(
            node=dict(
                label=nodes, color=node_colors, pad=16, thickness=18,
                line=dict(color="rgba(255,255,255,0.12)", width=0.5),
            ),
            link=dict(
                source=src, target=tgt, value=val,
                color="rgba(120,160,200,0.35)",
            ),
        ))
        fig = _theme(fig, height=460, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="risk_flow_sankey")
    else:
        st.info("No flow data available yet.")

    # --------------------------------------------------- Extended visualisations
    # ------------ Environmental Telemetry ------------------------------------
    st.markdown('<div class="fp-section-header">Environmental Telemetry</div>', unsafe_allow_html=True)
    et_a, et_b, et_c = st.columns(3)
    with et_a:
        hum_df = analytics.get_recent_humidity_readings(limit=200)
        if not hum_df.empty:
            hum_df["event_timestamp"] = pd.to_datetime(hum_df["event_timestamp"])
            fig = px.line(
                hum_df, x="event_timestamp", y="humidity_pct", color="temperature_status",
                color_discrete_map=STATUS_COLOR_MAP, markers=False,
                labels={"event_timestamp": "Time", "humidity_pct": "Humidity (%)", "temperature_status": "Status"},
            )
            fig = _theme(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, key="humidity_chart")
    with et_b:
        bat_df = analytics.get_recent_battery_readings(limit=200)
        if not bat_df.empty:
            bat_df["event_timestamp"] = pd.to_datetime(bat_df["event_timestamp"])
            fig = px.line(
                bat_df, x="event_timestamp", y="battery_pct", color="risk_level",
                color_discrete_map=RISK_COLOR_MAP, markers=False,
                labels={"event_timestamp": "Time", "battery_pct": "Battery (%)", "risk_level": "Risk Level"},
            )
            fig = _theme(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, key="battery_chart")
    with et_c:
        speed_df = analytics.get_speed_distribution()
        if not speed_df.empty:
            fig = px.bar(
                speed_df, x="bucket", y="count", color="count",
                color_continuous_scale=["#1F6FEB", "#22D3EE"],
                labels={"bucket": "Speed (km/h)", "count": "Readings"},
            )
            fig.update_traces(texttemplate="%{y}", textposition="outside")
            fig = _theme(fig, height=340, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="speed_hist")

    # ------------ Risk & Compliance Analysis ---------------------------------
    st.markdown('<div class="fp-section-header">Risk &amp; Compliance Analysis</div>', unsafe_allow_html=True)
    rc_a, rc_b = st.columns(2)
    with rc_a:
        risk_dist_df = analytics.get_risk_score_distribution()
        if not risk_dist_df.empty:
            fig = px.bar(
                risk_dist_df, x="bucket", y="count", color="count",
                color_continuous_scale=["#2ECC71", "#F39C12", "#C0392B"],
                labels={"bucket": "Risk Score", "count": "Readings"},
            )
            fig.update_traces(texttemplate="%{y}", textposition="outside")
            fig = _theme(fig, height=340, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="risk_hist")
    with rc_b:
        scatter_df = analytics.get_temperature_risk_scatter(limit=400)
        if not scatter_df.empty:
            fig = px.scatter(
                scatter_df, x="temperature_c", y="risk_score", color="risk_level",
                color_discrete_map=RISK_COLOR_MAP, hover_data=["food_category"],
                labels={"temperature_c": "Temperature (C)", "risk_score": "Risk Score", "risk_level": "Risk Level"},
            )
            fig = _theme(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, key="temp_risk_scatter")

    # ------------ Compliance by Food Category --------------------------------
    st.markdown('<div class="fp-section-header">Compliance by Food Category</div>', unsafe_allow_html=True)
    food_comp_df = analytics.get_food_category_compliance()
    if not food_comp_df.empty:
        fig = px.bar(
            food_comp_df, x="compliance_pct", y="food_category", orientation="h",
            color="compliance_pct", color_continuous_scale=["#C0392B", "#F39C12", "#2ECC71"],
            labels={"compliance_pct": "Temp Compliance (%)", "food_category": "Food Category"},
        )
        fig.update_traces(texttemplate="%{x:.1f}%", textposition="outside")
        fig = _theme(fig, height=360, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="food_compliance_bar")

    # ------------ Incident Analytics -----------------------------------------
    st.markdown('<div class="fp-section-header">Incident Analytics</div>', unsafe_allow_html=True)
    ia_a, ia_b, ia_c = st.columns(3)
    with ia_a:
        if not incident_severity_df.empty:
            sev_color = {"HIGH": CRITICAL_COLOR, "MEDIUM": HIGH_COLOR, "LOW": WARNING_COLOR}
            fig = go.Figure(data=[go.Pie(
                labels=incident_severity_df["severity"], values=incident_severity_df["count"], hole=0.6,
                marker=dict(colors=[sev_color.get(s, LIGHT_GRAY) for s in incident_severity_df["severity"]]),
            )])
            fig = _theme(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, key="incident_severity_donut")
    with ia_b:
        if not incident_type_df.empty:
            fig = px.bar(
                incident_type_df, x="incident_type", y="count", color="count",
                color_continuous_scale=["#22D3EE", "#1F6FEB"],
                labels={"incident_type": "Incident Type", "count": "Count"},
            )
            fig.update_layout(xaxis_tickangle=-30)
            fig = _theme(fig, height=340, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="incident_type_bar")
    with ia_c:
        inc_timeline_df = analytics.get_incident_timeline(limit=50)
        if not inc_timeline_df.empty:
            inc_timeline_df["incident_timestamp"] = pd.to_datetime(inc_timeline_df["incident_timestamp"])
            fig = px.scatter(
                inc_timeline_df, x="incident_timestamp", y="incident_type", color="severity",
                color_discrete_map={"HIGH": CRITICAL_COLOR, "MEDIUM": HIGH_COLOR, "LOW": WARNING_COLOR},
                labels={"incident_timestamp": "Time", "incident_type": "Incident Type", "severity": "Severity"},
            )
            fig = _theme(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, key="incident_timeline")

    # ------------ Warehouse & Delivery Operations ----------------------------
    st.markdown('<div class="fp-section-header">Warehouse &amp; Delivery Operations</div>', unsafe_allow_html=True)
    wo_a, wo_b, wo_c = st.columns(3)
    with wo_a:
        wh_df = analytics.get_warehouse_comparison()
        if not wh_df.empty:
            fig = px.bar(
                wh_df, x="warehouse", y="avg_risk", color="avg_risk",
                color_continuous_scale=["#2ECC71", "#F39C12", "#C0392B"],
                labels={"warehouse": "Warehouse", "avg_risk": "Avg Risk Score"},
            )
            fig = _theme(fig, height=340, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="warehouse_risk_bar")
    with wo_b:
        if not delivery_df.empty:
            fig = go.Figure(data=[go.Pie(
                labels=delivery_df["delivery_status"], values=delivery_df["count"], hole=0.6,
                marker=dict(colors=[ICE_BLUE, CYAN, SAFE_COLOR, WARNING_COLOR]),
            )])
            fig = _theme(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, key="delivery_donut")
    with wo_c:
        if not rejection_df.empty:
            fig = px.bar(
                rejection_df, x="rejection_reason", y="count", color="count",
                color_continuous_scale=["#E67E22", "#C0392B"],
                labels={"rejection_reason": "Rejection Reason", "count": "Count"},
            )
            fig.update_layout(xaxis_tickangle=-30)
            fig = _theme(fig, height=340, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="rejection_bar")

    # ------------ System Health & Correlations -------------------------------
    st.markdown('<div class="fp-section-header">System Health &amp; Correlations</div>', unsafe_allow_html=True)
    sh_a, sh_b = st.columns(2)
    with sh_a:
        health_score = analytics.get_system_health_score()
        gauge_color = SAFE_COLOR if health_score >= 75 else (WARNING_COLOR if health_score >= 50 else CRITICAL_COLOR)
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=health_score,
            number={"suffix": " / 100", "font": {"color": WHITE}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": LIGHT_GRAY},
                "bar": {"color": gauge_color},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 50], "color": "rgba(192,57,43,0.25)"},
                    {"range": [50, 75], "color": "rgba(243,156,18,0.25)"},
                    {"range": [75, 100], "color": "rgba(46,204,113,0.25)"},
                ],
            },
        ))
        fig = _theme(fig, height=420, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="system_health_gauge")
    with sh_b:
        corr_df = analytics.get_correlation_matrix()
        if not corr_df.empty:
            fig = px.imshow(
                corr_df, color_continuous_scale="RdBu", zmin=-1, zmax=1,
                text_auto=True, labels=dict(x="", y="", color="Corr"),
            )
            fig.update_layout(xaxis_title="", yaxis_title="")
            fig = _theme(fig, height=420, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="corr_heatmap")

    # ------------ Fleet Health & Status Trends -------------------------------
    st.markdown('<div class="fp-section-header">Fleet Health &amp; Status Trends</div>', unsafe_allow_html=True)
    ft_a, ft_b = st.columns(2)
    with ft_a:
        if not shipment_health_df.empty:
            avg_comp = float(shipment_health_df["temp_compliance"].mean())
            avg_risk_safety = float(100 - shipment_health_df["avg_risk"].mean())
            avg_batt = float(shipment_health_df["avg_battery"].mean())
            avg_door = float(shipment_health_df["door_discipline"].mean())
            cats = ["Temp Compliance", "Risk Safety", "Battery", "Door Discipline"]
            vals = [avg_comp, avg_risk_safety, avg_batt, avg_door]
            fig = go.Figure(go.Scatterpolar(
                r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself",
                line=dict(color=CYAN), fillcolor="rgba(34,211,238,0.15)",
            ))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])))
            fig = _theme(fig, height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="fleet_radar")
    with ft_b:
        status_time_df = analytics.get_status_over_time(limit=500)
        if not status_time_df.empty:
            status_pivot = status_time_df.pivot(
                index="minute", columns="temperature_status", values="count"
            ).fillna(0)
            order = [c for c in ["SAFE", "WARNING", "CRITICAL"] if c in status_pivot.columns]
            status_pivot = status_pivot[order]
            fig = px.area(
                status_pivot, color_discrete_map=STATUS_COLOR_MAP,
                labels={"value": "Readings", "minute": "Time", "temperature_status": "Status"},
            )
            fig = _theme(fig, height=400)
            st.plotly_chart(fig, use_container_width=True, key="status_area")

    # ------------ Pipeline Throughput ----------------------------------------
    st.markdown('<div class="fp-section-header">Pipeline Throughput</div>', unsafe_allow_html=True)
    tp_df = analytics.get_pipeline_throughput(limit=25)
    if not tp_df.empty:
        tp_df["run_index"] = list(range(1, len(tp_df) + 1))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=tp_df["run_index"], y=tp_df["rows_generated"], name="Generated",
                                 mode="lines+markers", line=dict(color=ICE_BLUE)))
        fig.add_trace(go.Scatter(x=tp_df["run_index"], y=tp_df["rows_processed"], name="Processed",
                                 mode="lines+markers", line=dict(color=SAFE_COLOR)))
        fig.add_trace(go.Scatter(x=tp_df["run_index"], y=tp_df["rows_rejected"], name="Rejected",
                                 mode="lines+markers", line=dict(color=CRITICAL_COLOR)))
        fig.add_trace(go.Scatter(x=tp_df["run_index"], y=tp_df["incidents_created"], name="Incidents",
                                 mode="lines+markers", line=dict(color=WARNING_COLOR)))
        fig.update_layout(xaxis_title="Pipeline Run", yaxis_title="Records")
        fig = _theme(fig, height=380)
        st.plotly_chart(fig, use_container_width=True, key="pipeline_throughput")

    # ---------------------------------------------------------- Shipment health
    st.markdown('<div class="fp-section-header">Shipment Health</div>', unsafe_allow_html=True)
    if not shipment_health_df.empty:
        display_df = shipment_health_df[[
            "shipment_id", "health_score", "avg_risk", "temp_compliance", "status"
        ]].head(15).rename(columns={
            "shipment_id": "Shipment", "health_score": "Health", "avg_risk": "Risk",
            "temp_compliance": "Temp Compliance", "status": "Status",
        })
        display_df["Risk"] = display_df["Risk"].round(1)
        display_df["Temp Compliance"] = display_df["Temp Compliance"].round(1)
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------- Incidents
    st.markdown('<div class="fp-section-header">Incident Monitoring</div>', unsafe_allow_html=True)
    incidents_df = analytics.get_recent_incidents(limit=20)
    if not incidents_df.empty:
        incidents_df = incidents_df.rename(columns={
            "incident_timestamp": "Timestamp", "shipment_id": "Shipment", "vehicle_id": "Vehicle",
            "incident_type": "Incident Type", "severity": "Severity", "description": "Description",
        })
        st.dataframe(incidents_df, use_container_width=True, hide_index=True)
    else:
        st.info("No incidents recorded yet.")

    # ---------------------------------------------------------- Pipeline health
    st.markdown('<div class="fp-section-header">Pipeline Health</div>', unsafe_allow_html=True)
    p1, p2, p3, p4, p5, p6 = st.columns(6)
    p1.metric("Records Generated", f"{pipeline_health['records_generated']:,}")
    p2.metric("Records Processed", f"{pipeline_health['records_processed']:,}")
    p3.metric("Records Rejected", f"{pipeline_health['records_rejected']:,}")
    p4.metric("Processing Success Rate", f"{pipeline_health['processing_success_rate']}%")
    p5.metric("Pipeline Runs", f"{pipeline_health['total_runs']:,}")
    p6.metric("Last Run Status", pipeline_health["last_run_status"])

    runs_df = analytics.get_recent_pipeline_runs(limit=8)
    if not runs_df.empty:
        st.dataframe(runs_df, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------- Data freshness
    st.markdown('<div class="fp-section-header">Data Freshness</div>', unsafe_allow_html=True)
    if freshness is not None:
        if freshness < 10:
            badge, label = SAFE_COLOR, "HEALTHY"
        elif freshness < 30:
            badge, label = WARNING_COLOR, "WARNING"
        else:
            badge, label = CRITICAL_COLOR, "CRITICAL"
        g1, g2 = st.columns(2)
        g1.metric("Latency Since Last Event", f"{freshness:.1f} s")
        g2.markdown(
            f'<div style="padding-top:1.6rem;"><span style="color:{badge}; font-weight:600;">{label}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No events processed yet.")


def _render_operations():
    st.markdown('<div class="fp-title">FrostPulse</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="fp-subtitle">Cold-Chain Intelligence &amp; Shipment Risk Monitoring</div>',
        unsafe_allow_html=True,
    )
    live_dashboard()
    st.markdown(
        '<div class="fp-footer">Made by Sourish Dey<br>FrostPulse — Cold-Chain Intelligence</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Top-level navigation between the two analytics layers
# ---------------------------------------------------------------------------

VIEW = st.radio(
    "Dashboard",
    ["Operations", "Business Analytics"],
    index=0,
    horizontal=True,
)

if VIEW == "Business Analytics":
    business_dashboard.render_business_dashboard()
else:
    _render_operations()
