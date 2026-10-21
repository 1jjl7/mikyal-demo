"""
make_sim.py - builds a SIMULATED store dataset for Mikyal.

Why: we have no real store data, so we create a realistic fake store to build
and test the engine. Numbers come from our field visits (3 stores in Buraydah,
20-21 Oct 2026) where possible, and are marked as assumptions otherwise.

What the simulation copies from the visits:
  - produce is ordered "by what ran out", in cartons, and leftovers stay on the
    shelf until they spoil (3-5 days)
  - bakery: pastries 16 per tray (+~5 if they sold out), samoli & bread in dough
    batches, chef adds/removes a batch after he sees the result
  - a weekly promo day (stores told us promos push sales; one store "doubles the qty")

Output (folder data/SIMULATED/):
  items.csv, calendar.csv, sales.csv, stock.csv, promos.csv
  true_demand.csv - what customers REALLY wanted (only the simulation knows it;
                    used to judge the engine, never shown as real data)
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42                      # fixed seed -> same "random" data every run
START, END = "2025-01-01", "2026-10-17"   # data ends Saturday -> demo day = Sunday (promo day)
OUT = Path(__file__).parent / "data" / "SIMULATED"

# ---------------------------------------------------------------------------
# 1) Items. base = normal daily demand.  source: "visit" or "assumption"
# ---------------------------------------------------------------------------
ITEMS = [
    # item,        category, unit,  base, shelf, cost,  price, pack, chef_qty, source
    ("طماطم",       "produce", "kg",    25,  5,   3.20,  4.95,  6,    0, "assumption"),
    ("خيار",        "produce", "kg",    15,  5,   3.90,  5.95,  5,    0, "assumption"),
    ("جزر",         "produce", "kg",    10,  5,   8.10, 12.50,  5,    0, "visit"),  # ~10 kg/day
    ("فلفل بارد",   "produce", "kg",     8,  5,   5.80,  8.95,  5,    0, "assumption"),
    ("موز",         "produce", "kg",    14,  4,   4.50,  6.95,  3,    0, "visit"),  # ~14 kg/day
    # bakery: pastries 16 per tray; samoli & bread in dough batches (pack = pieces per batch, ASSUMPTION)
    ("صامولي",      "bakery",  "piece", 60,  3,   0.40,  1.00, 20,   60, "visit"),
    ("صامولي حليب", "bakery",  "piece", 25,  3,   0.50,  1.50, 10,   40, "visit"),  # sells slowly
    ("خبز مصري",    "bakery",  "bag",  170,  3,   0.80,  2.00, 25,  200, "visit"),  # 200 bags baked
    ("كرواسون",     "bakery",  "piece", 12,  1,   0.90,  2.50,  1,   16, "visit"),  # tray of 16
    ("بيتزا",       "bakery",  "piece", 14,  1,   1.20,  3.00,  1,   16, "visit"),  # tray of 16
]
COLUMNS = ["item", "category", "unit", "base", "shelf_life_days",
           "unit_cost", "unit_price", "pack_size", "chef_qty", "base_source"]
FIXED_TRAY = {"كرواسون", "بيتزا"}

# Daily spoilage of produce while it sits on the shelf (ASSUMPTION).
# Staff in all 3 stores sort 2-5 times a day and throw out damaged pieces;
# "banana, apple and eggplant spoil fast". Bakery keeps until its expiry.
DAILY_SPOIL = {"طماطم": 0.06, "خيار": 0.05, "جزر": 0.03, "فلفل بارد": 0.05, "موز": 0.08}

# weekday pattern per category (from the visits). Mon=0 ... Thu=3, Fri=4, Sat=5, Sun=6
WEEKDAY = {
    "produce": {0: 0.90, 1: 0.90, 2: 1.00, 3: 1.25, 4: 1.20, 5: 1.00, 6: 0.90},
    "bakery":  {0: 1.00, 1: 1.00, 2: 1.00, 3: 1.30, 4: 0.70, 5: 1.00, 6: 1.00},
}
# how strong each event is (our simulation assumptions)
EVENT_EFFECT = {
    "produce": {"ramadan": 1.15, "eid": 0.85, "salary": 1.10, "holiday": 1.10},
    "bakery":  {"ramadan": 1.30, "eid": 0.80, "salary": 1.10, "holiday": 1.00},
}
PROMO_DAY = 6            # Sunday (one store told us "Sunday offers")
PROMO_LIFT = 1.5         # ASSUMPTION: staff only said promos "sell strongly"
PROMO_ITEMS_PER_WEEK = 2


# ---------------------------------------------------------------------------
# The shelf: stock is sold oldest-first and thrown away when it expires
# ---------------------------------------------------------------------------
class Shelf:
    def __init__(self):
        self.batches = []                         # each batch = [qty, days_left]

    def on_hand(self):
        return sum(q for q, _ in self.batches)

    def days_left(self):
        return min((d for _, d in self.batches), default=0)

    def receive(self, qty, shelf_life):
        if qty > 0:
            self.batches.append([qty, shelf_life])

    def sell(self, demand):
        sold = 0
        for b in self.batches:                    # oldest first (FIFO)
            take = min(b[0], demand - sold)
            b[0] -= take
            sold += take
        self.batches = [b for b in self.batches if b[0] > 1e-9]
        return sold

    def end_of_day(self, daily_spoil=0.0):
        """Age every batch by one day. What reaches 0 days is waste,
        plus a small share of the rest that got damaged today (produce)."""
        for b in self.batches:
            b[1] -= 1
        wasted = sum(q for q, d in self.batches if d <= 0)
        self.batches = [b for b in self.batches if b[1] > 0]
        for b in self.batches:
            damaged = b[0] * daily_spoil
            b[0] -= damaged
            wasted += damaged
        return wasted


# ---------------------------------------------------------------------------
# How the store orders TODAY (what staff told us in the visits)
# ---------------------------------------------------------------------------
def new_store_state(it):
    return {"last_sold": it["base"], "ran_out": False, "heavy_waste": False,
            "batch_qty": it["chef_qty"]}


def store_order(it, state, on_hand, promo_today):
    if it["item"] in FIXED_TRAY:
        # pastries: a tray of 16 every day; +~5 "by feel" if it sold out yesterday
        qty = it["chef_qty"] + (5 if state["ran_out"] else 0)
    elif it["category"] == "bakery":
        # samoli & bread: add a batch if it sold out, remove one if a lot was left
        if state["ran_out"]:
            state["batch_qty"] += it["pack_size"]
        elif state["heavy_waste"]:
            state["batch_qty"] = max(it["pack_size"], state["batch_qty"] - it["pack_size"])
        qty = state["batch_qty"]
    else:
        # produce (staff): "I order 5 kg, 3 kg sell -> I order the missing 3 kg.
        # I don't wait for the last piece; the old stock goes to the front."
        # -> top up what was sold (in cartons), +1 carton if it ran out
        cartons = math.ceil(state["last_sold"] / it["pack_size"]) + (1 if state["ran_out"] else 0)
        qty = cartons * it["pack_size"]
    if promo_today:
        qty *= 2                                  # one store: "on promo we double the qty"
    return qty


def update_store_state(state, demand, sold, ordered, wasted):
    state["last_sold"] = sold
    state["ran_out"] = demand > sold + 1e-9
    state["heavy_waste"] = wasted > 0.25 * max(ordered, 1)


# ---------------------------------------------------------------------------
# Calendar + promos
# ---------------------------------------------------------------------------
def build_calendar():
    """Dates checked: Ramadan 1447 = 18 Feb 2026 (Umm al-Qura); salary = 27th (royal order 2018).
    Eid dates are approximate."""
    def rng(a, b):
        return pd.date_range(a, b, freq="D")
    events = []
    for d in rng("2025-03-01", "2025-03-29"): events.append((d, "ramadan"))
    for d in rng("2026-02-18", "2026-03-19"): events.append((d, "ramadan"))
    for d in rng("2025-03-30", "2025-04-02"): events.append((d, "eid"))
    for d in rng("2026-03-20", "2026-03-23"): events.append((d, "eid"))
    for d in rng("2025-06-06", "2025-06-09"): events.append((d, "eid"))
    for d in rng("2026-05-26", "2026-05-29"): events.append((d, "eid"))
    for d in ["2025-02-22", "2025-09-23", "2026-02-22", "2026-09-23"]:
        events.append((pd.Timestamp(d), "holiday"))
    for d in rng(START, "2026-12-31"):             # future salary days too
        if 27 <= d.day <= 30:
            events.append((d, "salary"))
    return (pd.DataFrame(events, columns=["date", "event"])
              .drop_duplicates("date", keep="first").sort_values("date"))


def promo_items_on(day, items):
    """Every Sunday 2 produce items are on promo, rotating week by week."""
    if day.weekday() != PROMO_DAY:
        return set()
    produce = list(items.loc[items["category"] == "produce", "item"])
    week = day.isocalendar()[1]
    return {produce[(week + k) % len(produce)] for k in range(PROMO_ITEMS_PER_WEEK)}


# ---------------------------------------------------------------------------
# Simulate
# ---------------------------------------------------------------------------
def demand_for(it, day, event, promo, rng):
    d = (it["base"]
         * WEEKDAY[it["category"]][day.weekday()]
         * EVENT_EFFECT[it["category"]].get(event, 1.0)
         * (PROMO_LIFT if promo else 1.0)
         * rng.lognormal(0, 0.2))                 # +-20% noise, like real life
    # DEMO SCENARIO (declared): milk samoli slowly loses customers from July 2026
    if it["item"] == "صامولي حليب" and day >= pd.Timestamp("2026-07-01"):
        d *= 1 - 0.35 * min((day - pd.Timestamp("2026-07-01")).days / 106, 1)
    return round(d, 1) if it["unit"] == "kg" else round(d)


def main():
    items = pd.DataFrame(ITEMS, columns=COLUMNS)
    calendar = build_calendar()
    event_of = dict(zip(calendar["date"], calendar["event"]))
    rng = np.random.default_rng(SEED)

    rows, truth, stock = [], [], []
    for _, it in items.iterrows():
        shelf, state = Shelf(), new_store_state(it)
        for day in pd.date_range(START, END, freq="D"):
            ev = event_of.get(day, "none")
            promo = it["item"] in promo_items_on(day, items)
            demand = demand_for(it, day, ev, promo, rng)

            ordered = store_order(it, state, shelf.on_hand(), promo)
            shelf.receive(ordered, it["shelf_life_days"])
            sold = shelf.sell(demand)
            wasted = shelf.end_of_day(DAILY_SPOIL.get(it["item"], 0.0))
            update_store_state(state, demand, sold, ordered, wasted)

            rows.append((day.date(), it["item"], round(sold, 1), ordered, round(wasted, 1), int(promo)))
            truth.append((day.date(), it["item"], demand))
        for qty, days in shelf.batches:           # what is left on the evening of the last day,
            stock.append((it["item"], round(qty, 1), days))   # one row per batch

    sales = pd.DataFrame(rows, columns=["date", "item", "qty_sold", "qty_ordered", "qty_wasted", "promo"])

    # planned promos for the next two Sundays (so the engine knows about them)
    future = pd.date_range(pd.Timestamp(END) + pd.DateOffset(days=1), periods=14, freq="D")
    promos = [(d.date(), i) for d in future for i in sorted(promo_items_on(d, items))]

    # optional store settings (examples, so the options are visible in the demo):
    #   min_qty        - display minimum ("the shelf should look full")
    #   surplus_action - markdown (can discount / move to salad, juice...) | reduce | none
    items["min_qty"] = items["item"].map({"كرواسون": 16})
    items["surplus_action"] = np.where(items["category"] == "produce", "markdown", "reduce")

    OUT.mkdir(parents=True, exist_ok=True)
    items.drop(columns=["base", "chef_qty"]).to_csv(OUT / "items.csv", index=False, encoding="utf-8-sig")
    calendar.assign(factor="").to_csv(OUT / "calendar.csv", index=False, encoding="utf-8-sig")
    sales.to_csv(OUT / "sales.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(truth, columns=["date", "item", "true_demand"]).to_csv(
        OUT / "true_demand.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(stock, columns=["item", "qty_on_hand", "days_left"]).to_csv(
        OUT / "stock.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(promos, columns=["date", "item"]).to_csv(OUT / "promos.csv", index=False, encoding="utf-8-sig")

    # demo stock: the shelf as it would be if the store had followed Mikyal in the backtest
    # (the store's own shelf above is bloated by its habits -> "don't order" for most items).
    # Written here, once, so mikyal.py and backtest.py give the same result in any order.
    from backtest import simulate
    _, mikyal_shelf, _, _ = simulate(OUT)
    pd.DataFrame(mikyal_shelf, columns=["item", "qty_on_hand", "days_left"]).to_csv(
        OUT / "stock.csv", index=False, encoding="utf-8-sig")

    print(f"saved to {OUT}")
    print(f"days: {sales['date'].nunique()}, items: {sales['item'].nunique()}, promo rows: {sales['promo'].sum()}")
    s = sales.groupby("item").agg(avg_sold=("qty_sold", "mean"), avg_ordered=("qty_ordered", "mean"),
                                  avg_wasted=("qty_wasted", "mean")).round(1)
    s["waste_%"] = (sales.groupby("item")["qty_wasted"].sum()
                    / sales.groupby("item")["qty_ordered"].sum() * 100).round(1)
    print(s.to_string())


if __name__ == "__main__":
    main()
