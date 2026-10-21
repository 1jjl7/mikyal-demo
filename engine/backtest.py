"""
backtest.py - step 3: walk-forward backtest with a real shelf.

Idea: replay past days. Each method runs ITS OWN shelf: every morning it decides
an order using ONLY data before that day, customers come (true demand from the
simulation), stock is sold oldest-first, leftovers carry over, and what expires
or gets damaged is waste. At the end we compare, per method:

  waste  - what was thrown away                (hurts the planet + cost)
  lost   - customers who found an empty shelf   (hurts sales)
  WAPE   - how far the forecast was from real demand

Methods:
  mikyal     - our engine (forecast x calendar x promo, critical ratio, minus stock)
  store      - the store's own habits from the field visits (see make_sim.store_order)
  last_week  - "same day last week", minus stock
  avg_4wk    - "average of the last 4 weeks", minus stock

Run:  python backtest.py            (uses data/SIMULATED)
Out:  output/backtest.csv, output/backtest_summary.csv
"""

import math
import sys
from pathlib import Path

import pandas as pd

from make_sim import (COLUMNS, DAILY_SPOIL, ITEMS, Shelf, new_store_state,
                      store_order, update_store_state)

# the store's habits (base, chef_qty) live only in the simulation, not in items.csv
SIM_ITEMS = pd.DataFrame(ITEMS, columns=COLUMNS).set_index("item", drop=False)
from mikyal import HERE, event_on, load_data, plan_qty

METHODS = ["mikyal", "store", "last_week", "avg_4wk"]
METHOD_AR = {"mikyal": "مكيال", "store": "طريقة المتجر الحالية",
             "last_week": "نفس اليوم الأسبوع الماضي", "avg_4wk": "متوسط آخر 4 أسابيع"}
WARM_UP = 7          # days run before each test window and not counted (fills the shelves)


def test_windows(sales, calendar):
    """Last 8 weeks + Ramadan 2026 (so the Ramadan factor is really tested)."""
    last = sales["date"].max()
    recent = (last - pd.DateOffset(days=55), last)
    ram = calendar.loc[(calendar["event"] == "ramadan") & (calendar["date"].dt.year == 2026), "date"]
    return [recent, (ram.min(), ram.max())]


def to_order(qty, pack):
    pack = max(int(pack), 1)
    return math.ceil(max(qty, 0) / pack) * pack


def simulate(folder):
    """Replay the test windows. Writes nothing.
    Returns the daily rows and Mikyal's own shelf on the last evening (item, qty, days_left)."""
    folder = Path(folder)
    sales, items, calendar = load_data(folder)
    truth = pd.read_csv(folder / "true_demand.csv", parse_dates=["date"])
    sales = sales.merge(truth, on=["date", "item"], how="left")
    data_source = "simulated" if "SIMULATED" in str(folder).upper() else "real"

    rows, mikyal_shelf = [], []
    last_day = sales["date"].max()
    for start, end in test_windows(sales, calendar):
        days = pd.date_range(start - pd.DateOffset(days=WARM_UP), end, freq="D")
        for _, it in items.iterrows():
            s = sales[sales["item"] == it["item"]].set_index("date")
            shelves = {m: Shelf() for m in METHODS}
            store_it = SIM_ITEMS.loc[it["item"]]
            state = new_store_state(store_it)
            spoil = DAILY_SPOIL.get(it["item"], 0.0)

            for day in days:
                if day not in s.index:
                    continue
                hist = s[s.index < day].reset_index()
                demand = s.at[day, "true_demand"]
                promo = bool(s.at[day, "promo"])
                event, manual = event_on(calendar, day)

                preds, orders = {}, {}
                p = plan_qty(hist, it, day, event, manual,
                             on_hand=shelves["mikyal"].on_hand(), promo_today=promo)
                preds["mikyal"], orders["mikyal"] = p["forecast"], p["order"]

                orders["store"] = store_order(store_it, state, shelves["store"].on_hand(), promo)
                preds["store"] = orders["store"]

                preds["last_week"] = hist["qty_sold"].iloc[-7]
                preds["avg_4wk"] = hist["qty_sold"].tail(28).mean()
                for m in ("last_week", "avg_4wk"):
                    orders[m] = to_order(preds[m] - shelves[m].on_hand(), it["pack_size"])

                row = {"date": day.date(), "item": it["item"], "unit": it["unit"],
                       "event": event, "promo": int(promo), "actual": demand,
                       "counted": day >= start}
                for m in METHODS:
                    sh = shelves[m]
                    sh.receive(orders[m], it["shelf_life_days"])
                    sold = sh.sell(demand)
                    wasted = sh.end_of_day(spoil)
                    if m == "store":
                        update_store_state(state, demand, sold, orders[m], wasted)
                    row[f"pred_{m}"] = round(preds[m], 1)
                    row[f"order_{m}"] = orders[m]
                    row[f"waste_{m}"] = round(wasted, 2)
                    row[f"lost_{m}"] = round(demand - sold, 2)
                rows.append(row)

            if end == last_day:                        # Mikyal's own shelf on the last evening
                for qty, d_left in shelves["mikyal"].batches:
                    mikyal_shelf.append((it["item"], round(qty, 1), d_left))

    bt = pd.DataFrame(rows)
    bt = bt[bt["counted"]].drop(columns="counted")
    return bt, mikyal_shelf, items, data_source


def run(folder):
    bt, _, items, data_source = simulate(folder)

    # Group rows (ALL, ALL:produce, ALL:bakery) mix kg, pieces and bags, so every
    # quantity is weighted by unit_cost: one riyal of waste counts the same in any unit.
    # Per item the weight is constant, so the % are the plain unit %.
    cost = bt["item"].map(items.set_index("item")["unit_cost"])
    category = bt["item"].map(items.set_index("item")["category"])
    groups = (list(bt.groupby("item"))
              + [("ALL", bt)]
              + [(f"ALL:{c}", g) for c, g in bt.groupby(category)])
    summary = []
    for item, g in groups:
        w = cost[g.index]
        demand = (g["actual"] * w).sum()
        pct = lambda s: round((s * w).sum() / demand * 100, 1)
        for m in METHODS:
            err = g[f"pred_{m}"] - g["actual"]
            over = (g[f"order_{m}"] - g["actual"]).clip(lower=0)
            under = (g["actual"] - g[f"order_{m}"]).clip(lower=0)
            one = not item.startswith("ALL")          # quantities only per item (units differ)
            summary.append({
                "item": item, "method": m,
                "mae": round(err.abs().mean(), 2) if one else "",
                "wape": pct(err.abs()),
                "over_qty": round(over.sum(), 1) if one else "",
                "under_qty": round(under.sum(), 1) if one else "",
                "over_pct": pct(over),
                "under_pct": pct(under),
                "waste_qty": round(g[f"waste_{m}"].sum(), 1) if one else "",
                "lost_qty": round(g[f"lost_{m}"].sum(), 1) if one else "",
                "waste_pct": pct(g[f"waste_{m}"]),
                "lost_pct": pct(g[f"lost_{m}"]),
                "n_days": g["date"].nunique(),
                "data_source": data_source,
            })
    summary = pd.DataFrame(summary)

    out = HERE / "output"
    out.mkdir(exist_ok=True)
    bt.to_csv(out / "backtest.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(out / "backtest_summary.csv", index=False, encoding="utf-8-sig")
    return bt, summary


def tradeoff(folder, levels=(0.75, 0.85, 0.90, 0.95, 0.97, 0.98)):
    """Run the backtest for several service levels: less waste <-> fewer empty shelves.
    The store picks the balance it wants. Saved to output/service_tradeoff.csv."""
    import mikyal
    keep, rows = mikyal.SERVICE_MIN, []
    for level in levels:
        mikyal.SERVICE_MIN = level
        _, s = run(folder)
        a = s[s["item"] == "ALL"].set_index("method")
        rows.append({"service_level": level,
                     "mikyal_waste_pct": a.loc["mikyal", "waste_pct"],
                     "mikyal_lost_pct": a.loc["mikyal", "lost_pct"],
                     "store_waste_pct": a.loc["store", "waste_pct"],
                     "store_lost_pct": a.loc["store", "lost_pct"]})
    mikyal.SERVICE_MIN = keep
    out = pd.DataFrame(rows)
    out.to_csv(HERE / "output" / "service_tradeoff.csv", index=False, encoding="utf-8-sig")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = args[0] if args else HERE / "data" / "SIMULATED"
    if "--tradeoff" in sys.argv:
        print(tradeoff(folder).to_string(index=False))
        print()
    bt, summary = run(folder)
    print(f"test days: {bt['date'].nunique()}  |  actual = true demand (simulation)\n")

    allrow = summary[summary["item"] == "ALL"].set_index("method")
    print("ALL ITEMS (% of real demand, weighted by unit cost):")
    for m in METHODS:
        r = allrow.loc[m]
        print(f"  {METHOD_AR[m]:<26} forecast error {r.wape:>5}%   WASTE {r.waste_pct:>5}%   LOST {r.lost_pct:>5}%")

    print("\nPER ITEM - waste / lost (in the item's unit):")
    per = summary[~summary["item"].str.startswith("ALL")].pivot(index="item", columns="method",
                                                   values=["waste_qty", "lost_qty"])
    print(per.to_string())
