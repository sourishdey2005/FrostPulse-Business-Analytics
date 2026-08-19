"""
business_generator.py

Synthetic business / sales data generator for the FrostPulse Business
Analytics layer. Produces a coherent dataset of customers, products, and
order lines spanning the last 24 months, with revenue, cost, gross/net
profit, region, channel, category, discounts, and dates.

Kept separate from the cold-chain generator (generator.py) and the
pipeline (pipeline.py) to preserve the clean data / calculation / UI split.
"""

import math
import random
import uuid
from datetime import datetime, timedelta, timezone

from database import get_connection

REGIONS = {
    "West": {"Maharashtra": (19.0760, 72.8777), "Gujarat": (23.0225, 72.5714)},
    "North": {"Delhi": (28.6139, 77.2090), "Punjab": (30.9010, 75.8573)},
    "South": {"Karnataka": (12.9716, 77.5946), "Tamil Nadu": (13.0827, 80.2707)},
    "East": {"West Bengal": (22.5726, 88.3639), "Odisha": (20.2961, 85.8245)},
}

CHANNELS = ["Online", "Retail", "Wholesale", "Distributor", "Direct", "Franchise", "Export", "Government", "Institutional"]

CATEGORIES = [
    "Frozen Seafood", "Ice Cream", "Fresh Meat", "Dairy", "Fresh Produce",
    "Beverages", "Baked Goods", "Poultry", "Organic", "Ready-to-Eat",
    "Confectionery", "Snacks",
]

CATEGORY_PRICE = {
    "Frozen Seafood": (18.0, 45.0),
    "Ice Cream": (4.0, 12.0),
    "Fresh Meat": (12.0, 30.0),
    "Dairy": (3.0, 9.0),
    "Fresh Produce": (2.0, 7.0),
    "Beverages": (3.0, 10.0),
    "Baked Goods": (4.0, 15.0),
    "Poultry": (8.0, 22.0),
    "Organic": (5.0, 18.0),
    "Ready-to-Eat": (6.0, 16.0),
    "Confectionery": (2.0, 8.0),
    "Snacks": (2.0, 6.0),
}

CATEGORY_COST_RATIO = {
    "Frozen Seafood": 0.62,
    "Ice Cream": 0.55,
    "Fresh Meat": 0.68,
    "Dairy": 0.50,
    "Fresh Produce": 0.45,
    "Beverages": 0.40,
    "Baked Goods": 0.48,
    "Poultry": 0.58,
    "Organic": 0.52,
    "Ready-to-Eat": 0.45,
    "Confectionery": 0.38,
    "Snacks": 0.42,
}

OPEX_RATIO = 0.08  # operating expense as a fraction of revenue

PRODUCTS_PER_CATEGORY = 10
N_CUSTOMERS = 200
HISTORICAL_MONTHS = 24


def customer_master(n: int = N_CUSTOMERS) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        region = random.choice(list(REGIONS))
        state = random.choice(list(REGIONS[region]))
        rows.append({
            "customer_id": f"C{i:04d}",
            "customer_name": f"{REGIONS[region][state][1] and state} ColdChain {i:03d}",
            "region": region,
            "state": state,
            "city": state,
            "acquisition_channel": random.choice(CHANNELS),
            "first_order_date": None,
        })
    return rows


def product_master() -> list[dict]:
    rows = []
    pid = 1
    for cat in CATEGORIES:
        lo, hi = CATEGORY_PRICE[cat]
        for j in range(1, PRODUCTS_PER_CATEGORY + 1):
            list_price = round(random.uniform(lo, hi), 2)
            cost = round(list_price * CATEGORY_COST_RATIO[cat], 2)
            rows.append({
                "product_id": f"P{pid:03d}",
                "product_name": f"{cat} {j:02d}",
                "category": cat,
                "unit_cost": cost,
                "list_price": list_price,
            })
            pid += 1
    return rows


def generate_business_dataset(months: int = HISTORICAL_MONTHS) -> tuple[list, list, list]:
    """Build customers, products, and order-line rows spanning `months`."""
    customers = customer_master()
    products = product_master()
    first_seen: dict[str, str] = {}

    end = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = (end - timedelta(days=1)).replace(day=1)
    start = start - timedelta(days=30 * (months - 1))

    orders = []
    order_seq = 0
    cur = start
    month_idx = 0

    while cur < end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        days_in_month = (nxt - cur).days
        base = 45 + month_idx * 2.2 + 12 * abs(math.sin(month_idx / 2.0))
        n_orders = int(base + random.uniform(-10, 18))

        for _ in range(n_orders):
            day_offset = random.randint(0, max(days_in_month - 1, 0))
            odate = (cur + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            cust = random.choice(customers)
            cid = cust["customer_id"]
            if cid not in first_seen or odate < first_seen[cid]:
                first_seen[cid] = odate

            order_id = f"O{order_seq:06d}"
            order_seq += 1
            n_lines = random.randint(1, 3)
            for _ in range(n_lines):
                p = random.choice(products)
                qty = random.randint(1, 20)
                disc = round(random.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]), 2)
                unit_price = round(p["list_price"] * random.uniform(0.92, 1.08), 2)
                revenue = round(qty * unit_price * (1 - disc), 2)
                cost = round(qty * p["unit_cost"], 2)
                gross = round(revenue - cost, 2)
                net = round(gross - revenue * OPEX_RATIO, 2)
                orders.append({
                    "order_line_id": str(uuid.uuid4()),
                    "order_id": order_id,
                    "order_date": odate,
                    "hour": random.randint(6, 22),
                    "customer_id": cid,
                    "product_id": p["product_id"],
                    "region": cust["region"],
                    "state": cust["state"],
                    "city": cust["city"],
                    "channel": cust["acquisition_channel"],
                    "category": p["category"],
                    "quantity": qty,
                    "unit_price": unit_price,
                    "discount_pct": disc,
                    "revenue": revenue,
                    "cost": cost,
                    "gross_profit": gross,
                    "net_profit": net,
                })

        cur = nxt
        month_idx += 1

    for c in customers:
        c["first_order_date"] = first_seen.get(c["customer_id"], start.strftime("%Y-%m-%d"))

    return customers, products, orders


def seed_business_data(months: int = HISTORICAL_MONTHS) -> int:
    """Generate and persist the business dataset idempotently."""
    customers, products, orders = generate_business_dataset(months=months)
    with get_connection() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO dim_customer
               (customer_id, customer_name, region, state, city, acquisition_channel, first_order_date)
               VALUES (?,?,?,?,?,?,?)""",
            [(c["customer_id"], c["customer_name"], c["region"], c["state"], c["city"],
              c["acquisition_channel"], c["first_order_date"]) for c in customers],
        )
        conn.executemany(
            """INSERT OR IGNORE INTO dim_product
               (product_id, product_name, category, unit_cost, list_price)
               VALUES (?,?,?,?,?)""",
            [(p["product_id"], p["product_name"], p["category"], p["unit_cost"], p["list_price"])
             for p in products],
        )
        conn.executemany(
            """INSERT OR IGNORE INTO fact_order
               (order_line_id, order_id, order_date, hour, customer_id, product_id, region, state,
                city, channel, category, quantity, unit_price, discount_pct, revenue, cost,
                gross_profit, net_profit)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(o["order_line_id"], o["order_id"], o["order_date"], o["hour"],
              o["customer_id"], o["product_id"], o["region"], o["state"],
              o["city"], o["channel"], o["category"], o["quantity"],
              o["unit_price"], o["discount_pct"], o["revenue"], o["cost"],
              o["gross_profit"], o["net_profit"]) for o in orders],
        )
    return len(orders)


def _ensure_all_customers(conn):
    existing_channels = {r[0] for r in conn.execute("SELECT DISTINCT acquisition_channel FROM dim_customer;").fetchall()}
    missing = [c for c in CHANNELS if c not in existing_channels]
    if not missing:
        return
    new_customers = []
    cid = int(conn.execute("SELECT COUNT(*) FROM dim_customer;").fetchone()[0]) + 1
    for ch in missing:
        region = random.choice(list(REGIONS))
        state = random.choice(list(REGIONS[region]))
        new_customers.append((
            f"C{cid:04d}", f"{state} ColdChain {cid:03d}",
            region, state, state, ch,
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        ))
        cid += 1
    conn.executemany(
        """INSERT OR IGNORE INTO dim_customer
           (customer_id, customer_name, region, state, city, acquisition_channel, first_order_date)
           VALUES (?,?,?,?,?,?,?)""",
        new_customers,
    )


def _ensure_all_categories(conn):
    existing_cats = {r[0] for r in conn.execute("SELECT DISTINCT category FROM dim_product;").fetchall()}
    missing = [c for c in CATEGORIES if c not in existing_cats]
    if not missing:
        return
    new_products = []
    pid = int(conn.execute("SELECT COUNT(*) FROM dim_product;").fetchone()[0]) + 1
    for cat in missing:
        lo, hi = CATEGORY_PRICE[cat]
        list_price = round(random.uniform(lo, hi), 2)
        cost = round(list_price * CATEGORY_COST_RATIO[cat], 2)
        new_products.append((
            f"P{pid:03d}", f"{cat} 01", cat, cost, list_price,
        ))
        pid += 1
    conn.executemany(
        """INSERT OR IGNORE INTO dim_product
           (product_id, product_name, category, unit_cost, list_price)
           VALUES (?,?,?,?,?)""",
        new_products,
    )


def generate_business_batch(n: int = 12) -> int:
    """Append a small batch of recent orders (used for live refresh)."""
    with get_connection() as conn:
        _ensure_all_categories(conn)
        _ensure_all_customers(conn)
        prod_rows = conn.execute(
            "SELECT product_id, category, unit_cost, list_price FROM dim_product;"
        ).fetchall()
        cust_rows = conn.execute(
            "SELECT customer_id, region, state, city, acquisition_channel FROM dim_customer;"
        ).fetchall()

    if not prod_rows or not cust_rows:
        return 0

    products = [dict(p) for p in prod_rows]
    customers = [dict(c) for c in cust_rows]
    now = datetime.now(timezone.utc)

    orders = []
    order_seq = int(now.timestamp())
    for _ in range(n):
        cust = random.choice(customers)
        cid = cust["customer_id"]
        order_id = f"L{order_seq:08d}"
        order_seq += 1
        days_back = random.randint(0, 6)
        order_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        for _ in range(random.randint(1, 3)):
            p = random.choice(products)
            qty = random.randint(1, 20)
            disc = round(random.choice([0, 0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]), 2)
            unit_price = round(p["list_price"] * random.uniform(0.92, 1.08), 2)
            revenue = round(qty * unit_price * (1 - disc), 2)
            cost = round(qty * p["unit_cost"], 2)
            gross = round(revenue - cost, 2)
            net = round(gross - revenue * OPEX_RATIO, 2)
            orders.append((
                str(uuid.uuid4()), order_id, order_date, random.randint(6, 22), cid, p["product_id"],
                cust["region"], cust["state"], cust["city"], cust["acquisition_channel"],
                p["category"], qty, unit_price, disc, revenue, cost, gross, net,
            ))

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO fact_order
               (order_line_id, order_id, order_date, hour, customer_id, product_id, region, state,
                city, channel, category, quantity, unit_price, discount_pct, revenue, cost,
                gross_profit, net_profit)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            orders,
        )
    return len(orders)
