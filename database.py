"""
database.py

Responsible for SQLite connection handling, schema creation, indexes,
and safe database initialization for FrostPulse.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_DIR = Path("data")
DB_PATH = DB_DIR / "frostpulse.db"


@contextmanager
def get_connection():
    """Yield a short-lived SQLite connection with sane pragmas applied."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS raw_sensor_events (
        event_id TEXT PRIMARY KEY,
        event_timestamp TEXT NOT NULL,
        shipment_id TEXT,
        vehicle_id TEXT,
        warehouse TEXT,
        destination TEXT,
        food_category TEXT,
        temperature_c REAL,
        humidity_pct REAL,
        latitude REAL,
        longitude REAL,
        door_open INTEGER,
        battery_pct REAL,
        speed_kmh REAL,
        delivery_status TEXT,
        ingested_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_vehicle (
        vehicle_id TEXT PRIMARY KEY,
        vehicle_type TEXT,
        refrigeration_type TEXT,
        capacity_kg REAL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_shipment (
        shipment_id TEXT PRIMARY KEY,
        food_category TEXT,
        warehouse TEXT,
        destination TEXT,
        required_min_temp REAL,
        required_max_temp REAL,
        created_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_sensor_reading (
        event_id TEXT PRIMARY KEY,
        event_timestamp TEXT NOT NULL,
        shipment_id TEXT,
        vehicle_id TEXT,
        temperature_c REAL,
        humidity_pct REAL,
        latitude REAL,
        longitude REAL,
        door_open INTEGER,
        battery_pct REAL,
        speed_kmh REAL,
        temperature_status TEXT,
        risk_score REAL,
        risk_level TEXT,
        anomaly_flag INTEGER,
        processed_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_incident (
        incident_id TEXT PRIMARY KEY,
        event_id TEXT,
        shipment_id TEXT,
        vehicle_id TEXT,
        incident_type TEXT,
        severity TEXT,
        incident_timestamp TEXT,
        description TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rejected_events (
        rejection_id TEXT PRIMARY KEY,
        event_id TEXT,
        rejection_reason TEXT,
        raw_payload TEXT,
        rejected_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT,
        finished_at TEXT,
        rows_generated INTEGER,
        rows_processed INTEGER,
        rows_rejected INTEGER,
        incidents_created INTEGER,
        status TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS data_quality_results (
        quality_id TEXT PRIMARY KEY,
        run_id TEXT,
        check_name TEXT,
        records_checked INTEGER,
        failures INTEGER,
        status TEXT,
        created_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_customer (
        customer_id TEXT PRIMARY KEY,
        customer_name TEXT,
        region TEXT,
        state TEXT,
        city TEXT,
        acquisition_channel TEXT,
        first_order_date TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_product (
        product_id TEXT PRIMARY KEY,
        product_name TEXT,
        category TEXT,
        unit_cost REAL,
        list_price REAL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_order (
        order_line_id TEXT PRIMARY KEY,
        order_id TEXT,
        order_date TEXT,
        customer_id TEXT,
        product_id TEXT,
        region TEXT,
        state TEXT,
        city TEXT,
        channel TEXT,
        category TEXT,
        quantity INTEGER,
        unit_price REAL,
        discount_pct REAL,
        revenue REAL,
        cost REAL,
        gross_profit REAL,
        net_profit REAL
    );
    """,
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_sensor_events(event_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_fact_ts ON fact_sensor_reading(event_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_fact_shipment ON fact_sensor_reading(shipment_id);",
    "CREATE INDEX IF NOT EXISTS idx_fact_vehicle ON fact_sensor_reading(vehicle_id);",
    "CREATE INDEX IF NOT EXISTS idx_fact_anomaly ON fact_sensor_reading(anomaly_flag);",
    "CREATE INDEX IF NOT EXISTS idx_incident_ts ON fact_incident(incident_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_fact_order_date ON fact_order(order_date);",
    "CREATE INDEX IF NOT EXISTS idx_fact_order_customer ON fact_order(customer_id);",
    "CREATE INDEX IF NOT EXISTS idx_fact_order_product ON fact_order(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_fact_order_region ON fact_order(region);",
    "CREATE INDEX IF NOT EXISTS idx_fact_order_category ON fact_order(category);",
    "CREATE INDEX IF NOT EXISTS idx_fact_order_channel ON fact_order(channel);",
]


def initialize_database() -> bool:
    """
    Create the database, schema, and indexes if they do not already exist.
    Returns True if this call performed a fresh initialization.
    """
    is_new = not DB_PATH.exists()
    with get_connection() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        for stmt in INDEX_STATEMENTS:
            conn.execute(stmt)
        _migrate(conn)
        _ensure_schema(conn)
    return is_new


def _ensure_schema(conn):
    needed = {
        "raw_sensor_events", "dim_vehicle", "dim_shipment",
        "fact_sensor_reading", "fact_incident", "rejected_events",
        "pipeline_runs", "data_quality_results",
        "dim_customer", "dim_product", "fact_order",
    }
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    missing = needed - present
    if missing:
        for stmt in SCHEMA_STATEMENTS:
            try:
                conn.execute(stmt)
            except Exception:
                pass
        for stmt in INDEX_STATEMENTS:
            try:
                conn.execute(stmt)
            except Exception:
                pass
        _migrate(conn)


def _migrate(conn):
    try:
        conn.execute("ALTER TABLE fact_order ADD COLUMN hour INTEGER DEFAULT 12;")
    except Exception:
        pass


def table_row_count(table: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(f"SELECT COUNT(*) AS c FROM {table};")
        return cur.fetchone()["c"]
