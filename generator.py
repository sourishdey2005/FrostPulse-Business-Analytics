"""
generator.py

Responsible for generating realistic synthetic cold-chain telemetry,
including deliberate anomaly injection.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

VEHICLES = [f"V{i:03d}" for i in range(1, 31)]

WAREHOUSES = {
    "North Hub": (19.2183, 72.9781),
    "Central Hub": (19.0760, 72.8777),
    "East Hub": (19.1197, 72.9050),
    "South Hub": (18.9750, 72.8258),
    "West Hub": (19.0450, 72.8350),
    "Airport Hub": (19.0896, 72.8656),
    "Port Hub": (18.9500, 72.8100),
    "Industrial Hub": (19.1500, 72.9200),
}

DESTINATIONS = {
    "Retail District": (19.0330, 72.8570),
    "Restaurant District": (19.1075, 72.8263),
    "Airport": (19.0896, 72.8656),
    "Hospital Zone": (19.0176, 72.8562),
    "Market District": (18.9548, 72.8253),
    "Hotel District": (19.0600, 72.8700),
    "School Zone": (19.0800, 72.8400),
    "Office Park": (19.1000, 72.8900),
    "Residential Complex": (19.0400, 72.8300),
    "Sports Stadium": (19.0700, 72.8600),
}

FOOD_CATEGORIES = [
    "Frozen Seafood", "Ice Cream", "Fresh Meat", "Dairy", "Fresh Produce",
    "Beverages", "Baked Goods", "Poultry", "Organic", "Ready-to-Eat",
    "Confectionery", "Snacks",
]

TEMP_RANGES = {
    "Frozen Seafood": (-25.0, -12.0),
    "Ice Cream": (-30.0, -15.0),
    "Fresh Meat": (-2.0, 6.0),
    "Dairy": (0.0, 8.0),
    "Fresh Produce": (2.0, 12.0),
    "Beverages": (2.0, 10.0),
    "Baked Goods": (15.0, 25.0),
    "Poultry": (-2.0, 4.0),
    "Organic": (2.0, 10.0),
    "Ready-to-Eat": (2.0, 8.0),
    "Confectionery": (15.0, 25.0),
    "Snacks": (15.0, 25.0),
}

DELIVERY_STATUSES = ["IN_TRANSIT", "LOADING", "DELIVERED", "DELAYED", "CUSTOMS_HOLD", "RETURNED"]

_SHIPMENT_POOL = [f"SHIP-{i:04d}" for i in range(1, 61)]
_VEHICLE_TYPES = ["Reefer Truck", "Refrigerated Van", "Cold Container Truck"]
_REFRIGERATION_TYPES = ["Mechanical", "Cryogenic", "Eutectic Plate"]


def _rand_point_near(lat: float, lon: float, spread: float = 0.03) -> tuple:
    return round(lat + random.uniform(-spread, spread), 6), round(lon + random.uniform(-spread, spread), 6)


def vehicle_master_records() -> list[dict]:
    records = []
    for v in VEHICLES:
        records.append({
            "vehicle_id": v,
            "vehicle_type": random.choice(_VEHICLE_TYPES),
            "refrigeration_type": random.choice(_REFRIGERATION_TYPES),
            "capacity_kg": round(random.uniform(800, 4000), 1),
        })
    return records


def shipment_master_records() -> list[dict]:
    records = []
    now = datetime.now(timezone.utc).isoformat()
    for s in _SHIPMENT_POOL:
        category = random.choice(FOOD_CATEGORIES)
        low, high = TEMP_RANGES[category]
        records.append({
            "shipment_id": s,
            "food_category": category,
            "warehouse": random.choice(list(WAREHOUSES.keys())),
            "destination": random.choice(list(DESTINATIONS.keys())),
            "required_min_temp": low,
            "required_max_temp": high,
            "created_at": now,
        })
    return records


def generate_event(event_time: datetime | None = None) -> dict:
    """Generate a single synthetic raw sensor event, with occasional anomalies."""
    vehicle_id = random.choice(VEHICLES)
    shipment_id = random.choice(_SHIPMENT_POOL)
    category = random.choice(FOOD_CATEGORIES)
    warehouse = random.choice(list(WAREHOUSES.keys()))
    destination = random.choice(list(DESTINATIONS.keys()))

    low, high = TEMP_RANGES[category]
    is_anomaly = random.random() < 0.12

    if is_anomaly:
        breach = random.uniform(3.0, 12.0)
        temperature = round(random.choice([low - breach, high + breach]), 2)
    else:
        temperature = round(random.uniform(low, high), 2)

    humidity = round(random.uniform(25, 98), 1)
    battery = round(random.uniform(2, 100), 1)
    speed = round(random.uniform(0, 120), 1)
    door_open = 1 if random.random() < 0.08 else 0

    origin_lat, origin_lon = WAREHOUSES[warehouse]
    lat, lon = _rand_point_near(origin_lat, origin_lon, spread=random.uniform(0.02, 0.08))

    ts = event_time or datetime.now(timezone.utc)

    return {
        "event_id": str(uuid.uuid4()),
        "event_timestamp": ts.isoformat(),
        "shipment_id": shipment_id,
        "vehicle_id": vehicle_id,
        "warehouse": warehouse,
        "destination": destination,
        "food_category": category,
        "temperature_c": temperature,
        "humidity_pct": humidity,
        "latitude": lat,
        "longitude": lon,
        "door_open": door_open,
        "battery_pct": battery,
        "speed_kmh": speed,
        "delivery_status": random.choice(DELIVERY_STATUSES),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_batch(n: int, event_time: datetime | None = None) -> list[dict]:
    return [generate_event(event_time) for _ in range(n)]


def generate_historical_batch(count: int, span_minutes: int = 45) -> list[dict]:
    """Generate a batch of events spread over the last `span_minutes` minutes."""
    now = datetime.now(timezone.utc)
    events = []
    for _ in range(count):
        offset = random.uniform(0, span_minutes * 60)
        ts = now - timedelta(seconds=offset)
        events.append(generate_event(ts))
    events.sort(key=lambda e: e["event_timestamp"])
    return events
