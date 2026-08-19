"""
pipeline.py

Responsible for validation, cleaning, transformation, risk scoring,
anomaly detection, and incident generation for raw sensor events.
"""

import json
import uuid
from datetime import datetime, timezone

from database import get_connection
from generator import TEMP_RANGES

VALID_FOOD_CATEGORIES = set(TEMP_RANGES.keys())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_event(event: dict) -> tuple[bool, str]:
    """Run data-quality checks on a raw event. Returns (is_valid, reason)."""
    if not event.get("shipment_id"):
        return False, "null_shipment_id"
    if not event.get("vehicle_id"):
        return False, "null_vehicle_id"
    if not event.get("event_timestamp"):
        return False, "null_timestamp"

    temp = event.get("temperature_c")
    if temp is None or temp < -40 or temp > 40:
        return False, "invalid_temperature"

    humidity = event.get("humidity_pct")
    if humidity is None or humidity < 0 or humidity > 100:
        return False, "invalid_humidity"

    battery = event.get("battery_pct")
    if battery is None or battery < 0 or battery > 100:
        return False, "invalid_battery_pct"

    speed = event.get("speed_kmh")
    if speed is None or speed < 0 or speed > 160:
        return False, "invalid_speed"

    lat, lon = event.get("latitude"), event.get("longitude")
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return False, "invalid_coordinates"

    return True, ""


def temperature_status(event: dict) -> str:
    category = event.get("food_category")
    low, high = TEMP_RANGES.get(category, (-30, 30))
    temp = event["temperature_c"]
    if low <= temp <= high:
        return "SAFE"
    breach = min(abs(temp - low), abs(temp - high))
    return "CRITICAL" if breach > 5 else "WARNING"


def compute_risk_score(event: dict, temp_status: str) -> int:
    score = 0
    # Temperature anomaly: 0-60 points
    if temp_status == "CRITICAL":
        score += 60
    elif temp_status == "WARNING":
        score += 30
    # Door open: 0-15 points
    if event.get("door_open"):
        score += 15
    # Humidity > 80%: 0-10 points
    if event.get("humidity_pct", 0) > 80:
        score += 10
    # Battery < 30%: 0-10 points
    if event.get("battery_pct", 100) < 30:
        score += 10
    # High speed: 0-5 points
    if event.get("speed_kmh", 0) > 80:
        score += 5
    return min(score, 100)


def risk_level_from_score(score: int) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def _incidents_for_event(event: dict, temp_status: str, risk_score: int, risk_level: str) -> list[dict]:
    incidents = []
    ts = event["event_timestamp"]

    def add(incident_type: str, severity: str, description: str):
        incidents.append({
            "incident_id": str(uuid.uuid4()),
            "event_id": event["event_id"],
            "shipment_id": event["shipment_id"],
            "vehicle_id": event["vehicle_id"],
            "incident_type": incident_type,
            "severity": severity,
            "incident_timestamp": ts,
            "description": description,
        })

    if temp_status == "CRITICAL":
        add("TEMPERATURE_CRITICAL", "HIGH",
            f"Temperature {event['temperature_c']}C outside safe range for {event['food_category']}.")
    if risk_score >= 60:
        add("HIGH_RISK", "HIGH" if risk_level == "CRITICAL" else "MEDIUM",
            f"Shipment risk score reached {risk_score}.")
    if event.get("door_open"):
        add("DOOR_OPEN", "MEDIUM", "Cargo door opened during transit.")
    if event.get("battery_pct", 100) < 15:
        add("LOW_BATTERY", "LOW", f"Sensor battery at {event['battery_pct']}%.")

    return incidents


def run_pipeline(raw_events: list[dict]) -> dict:
    """
    Process a batch of raw events end-to-end: insert raw, validate,
    transform, score risk, detect incidents, and persist all outputs.
    """
    run_id = str(uuid.uuid4())
    started_at = _now()

    processed_rows = []
    rejected_rows = []
    incident_rows = []
    dq_failures = {
        "null_shipment_id": 0, "null_vehicle_id": 0, "null_timestamp": 0,
        "invalid_temperature": 0, "invalid_humidity": 0, "invalid_battery_pct": 0,
        "invalid_speed": 0, "invalid_coordinates": 0, "duplicate_event_id": 0,
    }
    seen_ids = set()

    for event in raw_events:
        if event["event_id"] in seen_ids:
            dq_failures["duplicate_event_id"] += 1
            rejected_rows.append((str(uuid.uuid4()), event["event_id"], "duplicate_event_id",
                                   json.dumps(event), _now()))
            continue
        seen_ids.add(event["event_id"])

        is_valid, reason = validate_event(event)
        if not is_valid:
            dq_failures[reason] = dq_failures.get(reason, 0) + 1
            rejected_rows.append((str(uuid.uuid4()), event["event_id"], reason,
                                   json.dumps(event), _now()))
            continue

        t_status = temperature_status(event)
        risk_score = compute_risk_score(event, t_status)
        risk_level = risk_level_from_score(risk_score)
        anomaly_flag = 1 if t_status != "SAFE" else 0

        processed_rows.append((
            event["event_id"], event["event_timestamp"], event["shipment_id"],
            event["vehicle_id"], event["temperature_c"], event["humidity_pct"],
            event["latitude"], event["longitude"], event["door_open"],
            event["battery_pct"], event["speed_kmh"], t_status, risk_score,
            risk_level, anomaly_flag, _now(),
        ))

        incident_rows.extend(_incidents_for_event(event, t_status, risk_score, risk_level))

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO raw_sensor_events
               (event_id, event_timestamp, shipment_id, vehicle_id, warehouse, destination,
                food_category, temperature_c, humidity_pct, latitude, longitude, door_open,
                battery_pct, speed_kmh, delivery_status, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(e["event_id"], e["event_timestamp"], e["shipment_id"], e["vehicle_id"],
              e["warehouse"], e["destination"], e["food_category"], e["temperature_c"],
              e["humidity_pct"], e["latitude"], e["longitude"], e["door_open"],
              e["battery_pct"], e["speed_kmh"], e["delivery_status"], e["ingested_at"])
             for e in raw_events],
        )

        if processed_rows:
            conn.executemany(
                """INSERT OR IGNORE INTO fact_sensor_reading
                   (event_id, event_timestamp, shipment_id, vehicle_id, temperature_c,
                    humidity_pct, latitude, longitude, door_open, battery_pct, speed_kmh,
                    temperature_status, risk_score, risk_level, anomaly_flag, processed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                processed_rows,
            )

        if incident_rows:
            conn.executemany(
                """INSERT OR IGNORE INTO fact_incident
                   (incident_id, event_id, shipment_id, vehicle_id, incident_type,
                    severity, incident_timestamp, description)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [(i["incident_id"], i["event_id"], i["shipment_id"], i["vehicle_id"],
                  i["incident_type"], i["severity"], i["incident_timestamp"], i["description"])
                 for i in incident_rows],
            )

        if rejected_rows:
            conn.executemany(
                """INSERT OR IGNORE INTO rejected_events
                   (rejection_id, event_id, rejection_reason, raw_payload, rejected_at)
                   VALUES (?,?,?,?,?)""",
                rejected_rows,
            )

        finished_at = _now()
        conn.execute(
            """INSERT INTO pipeline_runs
               (run_id, started_at, finished_at, rows_generated, rows_processed,
                rows_rejected, incidents_created, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, started_at, finished_at, len(raw_events), len(processed_rows),
             len(rejected_rows), len(incident_rows), "SUCCESS"),
        )

        dq_rows = []
        total = len(raw_events) or 1
        for check_name, failures in dq_failures.items():
            status = "PASS" if failures == 0 else "FAIL"
            dq_rows.append((str(uuid.uuid4()), run_id, check_name, total, failures, status, _now()))
        if dq_rows:
            conn.executemany(
                """INSERT INTO data_quality_results
                   (quality_id, run_id, check_name, records_checked, failures, status, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                dq_rows,
            )

    return {
        "run_id": run_id,
        "rows_generated": len(raw_events),
        "rows_processed": len(processed_rows),
        "rows_rejected": len(rejected_rows),
        "incidents_created": len(incident_rows),
    }


def seed_master_data():
    """Insert vehicle and shipment dimension records if not already present."""
    from generator import vehicle_master_records, shipment_master_records

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO dim_vehicle
               (vehicle_id, vehicle_type, refrigeration_type, capacity_kg)
               VALUES (?,?,?,?)""",
            [(v["vehicle_id"], v["vehicle_type"], v["refrigeration_type"], v["capacity_kg"])
             for v in vehicle_master_records()],
        )
        conn.executemany(
            """INSERT OR IGNORE INTO dim_shipment
               (shipment_id, food_category, warehouse, destination,
                required_min_temp, required_max_temp, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            [(s["shipment_id"], s["food_category"], s["warehouse"], s["destination"],
              s["required_min_temp"], s["required_max_temp"], s["created_at"])
             for s in shipment_master_records()],
        )
