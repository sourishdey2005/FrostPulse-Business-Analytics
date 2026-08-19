"""
live_business_generator.py

Background process that continuously generates new business orders
every second to simulate live data feeds, with occasional returns
and cancellations so KPIs naturally fluctuate up AND down.
"""

import random
import time
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from business_generator import generate_business_batch, get_connection

BATCH_SIZE = 50
SLEEP_SECONDS = 900
CANCEL_RATE = 0.50
RETURN_RATE = 0.30
PURGE_AGE_HOURS = 720

print(f"[LiveGenerator] Starting: ~{BATCH_SIZE} orders/{SLEEP_SECONDS}s, {CANCEL_RATE*100:.0f}% cancellations, {RETURN_RATE*100:.0f}% returns")

while True:
    try:
        n = generate_business_batch(n=BATCH_SIZE)
        if n:
            print(f"[LiveGenerator] Generated {n} new orders")

        with get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) AS c FROM fact_order;")
            total = cur.fetchone()["c"]

            if total > 50 and random.random() < CANCEL_RATE:
                cancel_n = min(random.randint(5, 15), max(5, int(total * 0.05)))
                rows = conn.execute(
                    f"SELECT order_line_id FROM fact_order ORDER BY RANDOM() LIMIT {cancel_n}"
                ).fetchall()
                for r in rows:
                    conn.execute("DELETE FROM fact_order WHERE order_line_id = ?", (r["order_line_id"],))
                print(f"[LiveGenerator] Cancelled {cancel_n} orders")

            if total > 50 and random.random() < RETURN_RATE:
                return_n = min(random.randint(3, 10), max(3, int(total * 0.02)))
                rows = conn.execute(
                    f"SELECT * FROM fact_order ORDER BY RANDOM() LIMIT {return_n}"
                ).fetchall()
                for r in rows:
                    conn.execute(
                        """INSERT OR REPLACE INTO fact_order
                           (order_line_id, order_id, order_date, hour, customer_id, product_id,
                            region, state, city, channel, category, quantity, unit_price,
                            discount_pct, revenue, cost, gross_profit, net_profit)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            str(__import__("uuid").uuid4()),
                            r["order_id"] + "-RET",
                            r["order_date"],
                            r["hour"],
                            r["customer_id"],
                            r["product_id"],
                            r["region"],
                            r["state"],
                            r["city"],
                            r["channel"],
                            r["category"],
                            -r["quantity"],
                            r["unit_price"],
                            r["discount_pct"],
                            -abs(r["revenue"]),
                            -abs(r["cost"]),
                            -abs(r["gross_profit"]),
                            -abs(r["net_profit"]),
                        ),
                    )
                print(f"[LiveGenerator] Processed {return_n} returns")

            if total > 1000 and random.random() < 0.05:
                cutoff_date = (datetime.now(timezone.utc) - timedelta(hours=720)).strftime("%Y-%m-%d")
                purge_n = conn.execute(
                    "DELETE FROM fact_order WHERE order_date < ?",
                    (cutoff_date,),
                ).rowcount
                if purge_n:
                    print(f"[LiveGenerator] Purged {purge_n} old rows")

    except Exception as e:
        print(f"[LiveGenerator] Error: {e}")
    time.sleep(SLEEP_SECONDS)
