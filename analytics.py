"""
analytics.py

Responsible for all analytical SQL queries that feed the dashboard:
KPI metrics, chart datasets, shipment health, pipeline health,
data quality, and freshness. Kept separate from UI code.
"""

from datetime import datetime, timezone
import pandas as pd

from database import get_connection

RECENT_LIMIT = 200


def _df(query: str, params: tuple = ()) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


# ---------------------------------------------------------------------------
# Top-level KPI metrics
# ---------------------------------------------------------------------------

def get_top_kpis() -> dict:
    with get_connection() as conn:
        total_shipments = conn.execute(
            "SELECT COUNT(DISTINCT shipment_id) AS c FROM fact_sensor_reading;"
        ).fetchone()["c"]
        active_vehicles = conn.execute(
            "SELECT COUNT(DISTINCT vehicle_id) AS c FROM fact_sensor_reading;"
        ).fetchone()["c"]
        total_readings = conn.execute(
            "SELECT COUNT(*) AS c FROM fact_sensor_reading;"
        ).fetchone()["c"]
        at_risk = conn.execute(
            "SELECT COUNT(DISTINCT shipment_id) AS c FROM fact_sensor_reading WHERE risk_level IN ('HIGH','CRITICAL');"
        ).fetchone()["c"]
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN temperature_status='SAFE' THEN 1 ELSE 0 END) AS safe_c,
                 COUNT(*) AS total_c
               FROM fact_sensor_reading;"""
        ).fetchone()
        compliance = (row["safe_c"] / row["total_c"] * 100) if row["total_c"] else 0.0
        avg_risk = conn.execute(
            "SELECT AVG(risk_score) AS a FROM fact_sensor_reading;"
        ).fetchone()["a"] or 0.0

    return {
        "total_shipments": total_shipments,
        "active_vehicles": active_vehicles,
        "total_readings": total_readings,
        "at_risk_shipments": at_risk,
        "temperature_compliance": round(compliance, 1),
        "avg_risk_score": round(avg_risk, 1),
    }


def get_second_kpis() -> dict:
    with get_connection() as conn:
        critical_incidents = conn.execute(
            "SELECT COUNT(*) AS c FROM fact_incident WHERE severity='HIGH';"
        ).fetchone()["c"]
        warning_incidents = conn.execute(
            "SELECT COUNT(*) AS c FROM fact_incident WHERE severity IN ('MEDIUM','LOW');"
        ).fetchone()["c"]
        avg_temp = conn.execute(
            "SELECT AVG(temperature_c) AS a FROM fact_sensor_reading;"
        ).fetchone()["a"] or 0.0
        avg_humidity = conn.execute(
            "SELECT AVG(humidity_pct) AS a FROM fact_sensor_reading;"
        ).fetchone()["a"] or 0.0
        low_battery = conn.execute(
            """SELECT COUNT(DISTINCT vehicle_id) AS c FROM fact_sensor_reading
               WHERE battery_pct < 30;"""
        ).fetchone()["c"]

        latest_run = conn.execute(
            "SELECT run_id FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;"
        ).fetchone()
        data_quality_score = 100.0
        if latest_run:
            row = conn.execute(
                """SELECT SUM(records_checked) AS checked, SUM(failures) AS failed
                   FROM data_quality_results WHERE run_id=?;""",
                (latest_run["run_id"],),
            ).fetchone()
            if row["checked"]:
                data_quality_score = max(0.0, 100.0 - (row["failed"] / row["checked"] * 100))

    return {
        "critical_incidents": critical_incidents,
        "warning_incidents": warning_incidents,
        "avg_temperature": round(avg_temp, 2),
        "avg_humidity": round(avg_humidity, 1),
        "low_battery_vehicles": low_battery,
        "data_quality_score": round(data_quality_score, 1),
    }


# ---------------------------------------------------------------------------
# Chart datasets
# ---------------------------------------------------------------------------

def get_recent_temperature_readings(limit: int = RECENT_LIMIT) -> pd.DataFrame:
    return _df(
        """SELECT event_timestamp, temperature_c, temperature_status, shipment_id, vehicle_id
           FROM fact_sensor_reading
           ORDER BY event_timestamp DESC
           LIMIT ?;""",
        (limit,),
    ).iloc[::-1].reset_index(drop=True)


def get_temperature_compliance_distribution() -> pd.DataFrame:
    return _df(
        """SELECT temperature_status AS status, COUNT(*) AS count
           FROM fact_sensor_reading
           GROUP BY temperature_status;"""
    )


def get_risk_distribution() -> pd.DataFrame:
    return _df(
        """SELECT risk_level, COUNT(DISTINCT shipment_id) AS count
           FROM fact_sensor_reading
           GROUP BY risk_level;"""
    )


def get_risk_by_warehouse() -> pd.DataFrame:
    return _df(
        """SELECT warehouse,
                  AVG(risk_score) AS avg_risk,
                  100.0 * SUM(CASE WHEN temperature_status='SAFE' THEN 1 ELSE 0 END) / COUNT(*) AS compliance_pct
           FROM fact_sensor_reading
           GROUP BY warehouse
           ORDER BY avg_risk DESC;"""
    )


def get_risk_by_food_category() -> pd.DataFrame:
    return _df(
        """SELECT ds.food_category AS food_category,
                  AVG(f.risk_score) AS avg_risk,
                  100.0 * SUM(CASE WHEN f.temperature_status='SAFE' THEN 1 ELSE 0 END) / COUNT(*) AS compliance_pct
           FROM fact_sensor_reading f
           JOIN dim_shipment ds ON ds.shipment_id = f.shipment_id
           GROUP BY ds.food_category
           ORDER BY avg_risk DESC;"""
    )


def get_vehicle_health() -> pd.DataFrame:
    return _df(
        """SELECT vehicle_id,
                  AVG(risk_score) AS avg_risk,
                  AVG(battery_pct) AS avg_battery,
                  100.0 * SUM(CASE WHEN temperature_status='SAFE' THEN 1 ELSE 0 END) / COUNT(*) AS compliance_pct
           FROM fact_sensor_reading
           GROUP BY vehicle_id
           ORDER BY avg_risk DESC;"""
    )


def get_latest_vehicle_locations() -> pd.DataFrame:
    return _df(
        """SELECT vehicle_id, latitude, longitude, temperature_c, risk_level, event_timestamp
           FROM fact_sensor_reading f
           WHERE event_timestamp = (
               SELECT MAX(event_timestamp) FROM fact_sensor_reading f2
               WHERE f2.vehicle_id = f.vehicle_id
           )
           GROUP BY vehicle_id;"""
    )


def get_shipment_health() -> pd.DataFrame:
    df = _df(
        """SELECT shipment_id,
                  AVG(risk_score) AS avg_risk,
                  100.0 * SUM(CASE WHEN temperature_status='SAFE' THEN 1 ELSE 0 END) / COUNT(*) AS temp_compliance,
                  AVG(battery_pct) AS avg_battery,
                  100.0 * SUM(CASE WHEN door_open=0 THEN 1 ELSE 0 END) / COUNT(*) AS door_discipline
           FROM fact_sensor_reading
           GROUP BY shipment_id;"""
    )
    if df.empty:
        return df
    df["health_score"] = (
        df["temp_compliance"] * 0.4
        + (100 - df["avg_risk"]) * 0.3
        + df["avg_battery"] * 0.15
        + df["door_discipline"] * 0.15
    ).round(1)
    df["status"] = df["health_score"].apply(
        lambda h: "HEALTHY" if h >= 75 else ("WATCH" if h >= 50 else "AT RISK")
    )
    return df.sort_values("health_score").reset_index(drop=True)


def get_recent_incidents(limit: int = 20) -> pd.DataFrame:
    return _df(
        """SELECT incident_timestamp, shipment_id, vehicle_id, incident_type, severity, description
           FROM fact_incident
           ORDER BY incident_timestamp DESC
           LIMIT ?;""",
        (limit,),
    )


def get_incident_severity_counts() -> pd.DataFrame:
    return _df(
        """SELECT severity, COUNT(*) AS count FROM fact_incident GROUP BY severity;"""
    )


def get_incident_type_counts() -> pd.DataFrame:
    return _df(
        """SELECT incident_type, COUNT(*) AS count FROM fact_incident GROUP BY incident_type ORDER BY count DESC;"""
    )


# ---------------------------------------------------------------------------
# Pipeline health / data engineering metrics
# ---------------------------------------------------------------------------

def get_pipeline_health() -> dict:
    with get_connection() as conn:
        latest = conn.execute(
            """SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;"""
        ).fetchone()
        totals = conn.execute(
            """SELECT SUM(rows_generated) AS gen, SUM(rows_processed) AS proc,
                      SUM(rows_rejected) AS rej, COUNT(*) AS runs
               FROM pipeline_runs;"""
        ).fetchone()

    generated = totals["gen"] or 0
    processed = totals["proc"] or 0
    rejected = totals["rej"] or 0
    success_rate = (processed / generated * 100) if generated else 100.0

    return {
        "records_generated": generated,
        "records_processed": processed,
        "records_rejected": rejected,
        "processing_success_rate": round(success_rate, 1),
        "total_runs": totals["runs"] or 0,
        "last_run_status": latest["status"] if latest else "N/A",
        "last_run_finished_at": latest["finished_at"] if latest else None,
    }


def get_recent_pipeline_runs(limit: int = 10) -> pd.DataFrame:
    return _df(
        """SELECT started_at, finished_at, rows_generated, rows_processed,
                  rows_rejected, incidents_created, status
           FROM pipeline_runs
           ORDER BY started_at DESC
           LIMIT ?;""",
        (limit,),
    )


def get_data_quality_summary() -> pd.DataFrame:
    return _df(
        """SELECT check_name, SUM(records_checked) AS records_checked,
                  SUM(failures) AS failures,
                  CASE WHEN SUM(failures) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
           FROM data_quality_results
           GROUP BY check_name;"""
    )


def get_rejection_reasons() -> pd.DataFrame:
    return _df(
        """SELECT rejection_reason, COUNT(*) AS count
           FROM rejected_events
           GROUP BY rejection_reason
           ORDER BY count DESC;"""
    )


def get_data_freshness_seconds() -> float | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(event_timestamp) AS latest FROM fact_sensor_reading;"
        ).fetchone()
    if not row or not row["latest"]:
        return None
    latest_ts = datetime.fromisoformat(row["latest"])
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - latest_ts
    return max(delta.total_seconds(), 0.0)


def get_status_by_warehouse() -> pd.DataFrame:
    return _df(
        """SELECT r.warehouse AS warehouse,
                  COUNT(*) AS readings,
                  AVG(f.risk_score) AS avg_risk
           FROM fact_sensor_reading f
           JOIN raw_sensor_events r ON r.event_id = f.event_id
           GROUP BY r.warehouse
           ORDER BY avg_risk DESC;"""
    )


def get_delivery_status_counts() -> pd.DataFrame:
    return _df(
        """SELECT delivery_status, COUNT(*) AS count
           FROM raw_sensor_events
           GROUP BY delivery_status;"""
    )


def get_anomaly_rate() -> float:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT SUM(anomaly_flag) AS anomalies, COUNT(*) AS total
               FROM fact_sensor_reading;"""
        ).fetchone()
    if not row or not row["total"]:
        return 0.0
    return round((row["anomalies"] or 0) / row["total"] * 100, 1)


# ---------------------------------------------------------------------------
# Extended analytics (charts added after initial release)
# ---------------------------------------------------------------------------


def get_recent_humidity_readings(limit: int = RECENT_LIMIT) -> pd.DataFrame:
    return _df(
        """SELECT event_timestamp, humidity_pct, temperature_status, shipment_id, vehicle_id
           FROM fact_sensor_reading
           ORDER BY event_timestamp DESC
           LIMIT ?;""",
        (limit,),
    ).iloc[::-1].reset_index(drop=True)


def get_recent_battery_readings(limit: int = RECENT_LIMIT) -> pd.DataFrame:
    return _df(
        """SELECT event_timestamp, battery_pct, risk_level, shipment_id, vehicle_id
           FROM fact_sensor_reading
           ORDER BY event_timestamp DESC
           LIMIT ?;""",
        (limit,),
    ).iloc[::-1].reset_index(drop=True)


def get_recent_risk_series(limit: int = RECENT_LIMIT) -> pd.DataFrame:
    return _df(
        """SELECT event_timestamp, risk_score, risk_level, shipment_id, vehicle_id
           FROM fact_sensor_reading
           ORDER BY event_timestamp DESC
           LIMIT ?;""",
        (limit,),
    ).iloc[::-1].reset_index(drop=True)


def get_risk_score_distribution() -> pd.DataFrame:
    return _df(
        """SELECT CAST(risk_score / 5 AS INTEGER) * 5 AS bucket, COUNT(*) AS count
           FROM fact_sensor_reading
           GROUP BY bucket
           ORDER BY bucket;"""
    )


def get_temperature_risk_scatter(limit: int = 300) -> pd.DataFrame:
    return _df(
        """SELECT f.temperature_c, f.risk_score, ds.food_category, f.risk_level, f.shipment_id
           FROM fact_sensor_reading f
           JOIN dim_shipment ds ON ds.shipment_id = f.shipment_id
           ORDER BY f.event_timestamp DESC
           LIMIT ?;""",
        (limit,),
    )


def get_speed_distribution() -> pd.DataFrame:
    return _df(
        """SELECT CAST(speed_kmh / 10 AS INTEGER) * 10 AS bucket, COUNT(*) AS count
           FROM fact_sensor_reading
           GROUP BY bucket
           ORDER BY bucket;"""
    )


def get_status_over_time(limit: int = 500) -> pd.DataFrame:
    return _df(
        """SELECT substr(event_timestamp, 1, 16) AS minute, temperature_status, COUNT(*) AS count
           FROM fact_sensor_reading
           GROUP BY minute, temperature_status
           ORDER BY minute;"""
    )


def get_door_open_trend(limit: int = 500) -> pd.DataFrame:
    return _df(
        """SELECT substr(event_timestamp, 1, 16) AS minute,
                    SUM(door_open) AS door_opens,
                    COUNT(*) AS total
           FROM fact_sensor_reading
           GROUP BY minute
           ORDER BY minute;"""
    )


def get_incident_timeline(limit: int = 50) -> pd.DataFrame:
    return _df(
        """SELECT incident_timestamp, severity, incident_type, shipment_id, vehicle_id
           FROM fact_incident
           ORDER BY incident_timestamp DESC
           LIMIT ?;""",
        (limit,),
    ).iloc[::-1].reset_index(drop=True)


def get_warehouse_comparison() -> pd.DataFrame:
    return _df(
        """SELECT r.warehouse AS warehouse,
                  COUNT(*) AS readings,
                  AVG(f.risk_score) AS avg_risk,
                  100.0 * SUM(CASE WHEN f.temperature_status='SAFE' THEN 1 ELSE 0 END) / COUNT(*) AS compliance_pct
           FROM fact_sensor_reading f
           JOIN raw_sensor_events r ON r.event_id = f.event_id
           GROUP BY r.warehouse
           ORDER BY avg_risk DESC;"""
    )


def get_food_category_compliance() -> pd.DataFrame:
    return _df(
        """SELECT ds.food_category AS food_category,
                  100.0 * SUM(CASE WHEN f.temperature_status='SAFE' THEN 1 ELSE 0 END) / COUNT(*) AS compliance_pct,
                  AVG(f.humidity_pct) AS avg_humidity,
                  AVG(f.risk_score) AS avg_risk
           FROM fact_sensor_reading f
           JOIN dim_shipment ds ON ds.shipment_id = f.shipment_id
           GROUP BY ds.food_category
           ORDER BY compliance_pct DESC;"""
    )


def get_pipeline_throughput(limit: int = 25) -> pd.DataFrame:
    return _df(
        """SELECT started_at, rows_generated, rows_processed, rows_rejected, incidents_created
           FROM pipeline_runs
           ORDER BY started_at DESC
           LIMIT ?;""",
        (limit,),
    ).iloc[::-1].reset_index(drop=True)


def get_hourly_reading_counts() -> pd.DataFrame:
    return _df(
        """SELECT substr(event_timestamp, 1, 13) AS hour, COUNT(*) AS count
           FROM fact_sensor_reading
           GROUP BY hour
           ORDER BY hour;"""
    )


def get_warehouse_food_risk_flow() -> pd.DataFrame:
    return _df(
        """SELECT r.warehouse AS warehouse,
                  ds.food_category AS food_category,
                  f.risk_level AS risk_level,
                  COUNT(*) AS count
           FROM fact_sensor_reading f
           JOIN raw_sensor_events r ON r.event_id = f.event_id
           JOIN dim_shipment ds ON ds.shipment_id = f.shipment_id
           GROUP BY r.warehouse, ds.food_category, f.risk_level;"""
    )


def get_correlation_matrix() -> pd.DataFrame:
    df = _df(
        """SELECT temperature_c, humidity_pct, battery_pct, speed_kmh, risk_score, door_open
           FROM fact_sensor_reading;"""
    )
    if df.empty:
        return df
    return df.corr().round(2)


def get_system_health_score() -> float:
    """Composite 0-100 health score across compliance, risk, battery and data quality."""
    top = get_top_kpis()
    second = get_second_kpis()
    shipment_health_df = get_shipment_health()
    if shipment_health_df.empty:
        return 0.0
    avg_health = float(shipment_health_df["health_score"].mean())
    compliance = top["temperature_compliance"] or 0.0
    data_quality = second["data_quality_score"] or 0.0
    score = compliance * 0.35 + avg_health * 0.35 + data_quality * 0.30
    return round(score, 1)
