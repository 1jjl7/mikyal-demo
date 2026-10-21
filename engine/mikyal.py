"""
mikyal.py - the Mikyal engine (step 2: forecast + recommendation + reason).

How to run:
    python mikyal.py                       # uses data/SIMULATED, forecasts the day after the last date
    python mikyal.py data/SIMULATED 2026-10-22

Inputs  (in the data folder): sales.csv, items.csv, calendar.csv
Output  (in output/):         recommendations.csv
"""

import math
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd

HERE = Path(__file__).parent
WEEKS_BACK = 4             # baseline = mean of the last 4 same weekdays
MIN_EVENT_DAYS = 5         # need at least 5 past days of an event to learn its factor
SERVICE_MIN = 0.97         # default service level (store setting, see critical_ratio).
                           # 0.97 = fewer empty shelves than the store's current habit in the backtest
SHORT_LIFE_MIN = 0.85      # default for 1-day items (leftovers are thrown away at night).
                           # 0.85 = less waste AND fewer empty shelves than the store for
                           # croissant & pizza in the backtest (0.80 already runs out more)

WEEKDAY_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
EVENT_AR = {"ramadan": "رمضان", "eid": "العيد", "salary": "أيام الراتب", "holiday": "إجازة رسمية"}
UNIT_AR = {"kg": "كجم", "piece": "حبة", "bag": "كيس"}


# ---------------------------------------------------------------------------
# Load the data
# ---------------------------------------------------------------------------
def load_data(folder):
    folder = Path(folder)
    sales = pd.read_csv(folder / "sales.csv", parse_dates=["date"])
    items = pd.read_csv(folder / "items.csv")
    calendar = pd.read_csv(folder / "calendar.csv", parse_dates=["date"])

    if "promo" not in sales.columns:                 # optional column
        sales["promo"] = 0
    sales["promo"] = sales["promo"].fillna(0).astype(int)
    # attach the event of each day ("none" on normal days)
    sales = sales.merge(calendar[["date", "event"]], on="date", how="left")
    sales["event"] = sales["event"].fillna("none")
    sales["weekday"] = sales["date"].dt.weekday
    return sales, items, calendar


def event_on(calendar, day):
    """Which event (if any) is on this day, and its manual factor (if the manager set one)."""
    row = calendar[calendar["date"] == day]
    if row.empty:
        return "none", None
    factor = row["factor"].iloc[0] if "factor" in row.columns else None
    return row["event"].iloc[0], (None if pd.isna(factor) or factor == "" else float(factor))


# ---------------------------------------------------------------------------
# Forecast ONE item for ONE day, using only data BEFORE that day
# (this function is reused by the backtest in step 3)
# ---------------------------------------------------------------------------
def load_promos(folder):
    """Optional promos.csv (date, item): promos already planned for coming days."""
    f = Path(folder) / "promos.csv"
    if not f.exists():
        return set()
    p = pd.read_csv(f, parse_dates=["date"])
    return set(zip(p["date"], p["item"]))


def promo_factor(history):
    """On past promo days (normal calendar days only), how much more did we sell
    than a normal day with the same weekday? (All 3 stores told us promos push sales.)"""
    normal = history[(history["event"] == "none") & (history["promo"] == 0)]
    wd_mean = normal.groupby("weekday")["qty_sold"].mean()
    past = history[(history["promo"] == 1) & (history["event"] == "none")]
    if len(past) < MIN_EVENT_DAYS:
        return 1.0, "not_enough_data", len(past)
    ratios = past["qty_sold"] / past["weekday"].map(wd_mean)
    return float(ratios.mean()), "learned", len(past)


def forecast(history, day, event, manual_factor=None):
    """
    history: sales rows of one item, all BEFORE `day`
    returns: baseline, factor, forecast, factor_source
    """
    normal = history[(history["event"] == "none") & (history["promo"] == 0)]

    # 1) baseline: mean of the last 4 normal days with the same weekday
    same_wd = normal[normal["weekday"] == day.weekday()].tail(WEEKS_BACK)
    if same_wd.empty:                                 # very short history -> plain mean
        same_wd = normal.tail(7)
    baseline = same_wd["qty_sold"].mean()

    # 2) calendar factor
    if event == "none":
        factor, source = 1.0, "none"
    elif manual_factor is not None:
        factor, source = manual_factor, "manual"
    else:
        # learn it: on past days of this event, how much did we sell
        # compared to a normal day with the same weekday?
        wd_normal_mean = normal.groupby("weekday")["qty_sold"].mean()
        past = history[(history["event"] == event) & (history["promo"] == 0)]
        if len(past) >= MIN_EVENT_DAYS:
            ratios = past["qty_sold"] / past["weekday"].map(wd_normal_mean)
            factor, source = float(ratios.mean()), "learned"
        else:
            factor, source = 1.0, "not_enough_data"

    return baseline, factor, baseline * factor, source


# ---------------------------------------------------------------------------
# Step 4a) critical ratio: is running out or throwing away more expensive?
# ---------------------------------------------------------------------------
def critical_ratio(item_row):
    """
    Cu = cost of ONE unit too few  = the profit we lose  (price - cost)
    Co = cost of ONE unit too many = what we throw away  (cost - salvage)
    CR = Cu / (Cu + Co)  -> above 0.5: order a bit MORE than the forecast,
                            below 0.5: order a bit LESS.
    Capped to 0.3..0.9 so one strange price can't push the order too far.
    """
    salvage = item_row.get("salvage_value", 0)
    salvage = 0 if pd.isna(salvage) else salvage
    cu = item_row["unit_price"] - item_row["unit_cost"]
    co = item_row["unit_cost"] - salvage
    if pd.isna(cu) or pd.isna(co) or cu + co <= 0:
        cr = 0.5                                      # no cost data -> plain forecast
    else:
        cr = cu / (cu + co)
    # service level: the store decides how often it accepts an empty shelf
    # (stores told us they hate empty shelves: "if it runs out we add more").
    # Optional column service_level in items.csv, default SERVICE_MIN.
    level = item_row.get("service_level")
    if level is not None and not pd.isna(level):
        return min(max(cr, float(level)), 0.99)
    # 1-day items (pastries, pizza): every unit left at night is thrown away, it can't
    # sell tomorrow, so a 97% floor there means daily waste. They get a lower floor.
    if item_row["shelf_life_days"] <= 1:
        return min(max(cr, min(SHORT_LIFE_MIN, SERVICE_MIN)), 0.99)
    return min(max(cr, SERVICE_MIN), 0.99)


def safety_qty(history, day, forecast_qty, cr):
    """
    How much to add (or remove) around the forecast.
    sigma = how much this weekday's sales jump around (std of the last 8 same weekdays).
    z     = how many sigmas to move, from the critical ratio (normal distribution).
    """
    normal = history[(history["event"] == "none") & (history["promo"] == 0)]
    sigma = normal[normal["weekday"] == day.weekday()]["qty_sold"].tail(8).std()
    sigma = 0 if pd.isna(sigma) else sigma
    z = NormalDist().inv_cdf(cr)
    return max(forecast_qty + z * sigma, 0)


def to_packs(qty, pack):
    pack = max(int(pack), 1)
    return math.ceil(max(qty, 0) / pack) * pack


def plan_qty(history, item_row, day, event, manual_factor=None, on_hand=0, promo_today=False):
    """
    Everything for one item & one day (used by run() and by the backtest):
    forecast (x promo) -> critical ratio -> minus usable stock -> round to cartons/batches.
    """
    baseline, factor, fc, source = forecast(history, day, event, manual_factor)
    pf, p_source, n_promo = (promo_factor(history) if promo_today else (1.0, "none", 0))
    fc *= pf
    cr = critical_ratio(item_row)
    target = safety_qty(history, day, fc, cr)
    order = to_packs(target - on_hand, item_row["pack_size"])
    return dict(baseline=baseline, factor=factor, forecast=fc, source=source,
                promo_factor=pf, promo_source=p_source, n_promo=n_promo,
                cr=cr, target=target, order=order)


# ---------------------------------------------------------------------------
# Step 4b) early surplus alert - the advice depends on the category
# (field visit: produce -> salad / cut cups / juice / offer plates;
#               bakery  -> NO outlet, after 3 days it goes to sheep)
# ---------------------------------------------------------------------------
TREND_LIMIT = 0.80        # sales fell more than 20% vs the month before
WASTE_LIMIT = 0.20        # more than 20% of what we ordered was thrown away


def slow_signals(history):
    """
    Step 5 - two simple numbers per item:
      trend : sales of the last 28 days / the same 28 days 3 months ago
              (Ramadan & Eid removed) - catches a SLOW decline, not just a sudden drop
      waste : share of the ordered qty that was wasted in the last 14 days (if we have it)
    """
    trend, waste = None, None
    calm = history[~history["event"].isin(["ramadan", "eid"])]
    if len(calm) >= 112:
        prev = calm["qty_sold"].iloc[-112:-84].sum()
        if prev > 0:
            trend = calm["qty_sold"].iloc[-28:].sum() / prev
    if {"qty_wasted", "qty_ordered"} <= set(history.columns):
        recent = history.tail(14)
        if recent["qty_ordered"].sum() > 0:
            waste = recent["qty_wasted"].sum() / recent["qty_ordered"].sum()
    return trend, waste


def slow_mover_note(trend, waste, category_waste):
    """
    Flag only what stands out, so the manager doesn't learn to ignore alerts:
      - sales fell more than 20%, or
      - waste above 20% AND 1.5x the usual waste of its department (produce / bakery)
    """
    notes = []
    if trend is not None and trend < TREND_LIMIT:
        notes.append(f"مبيعاته آخر شهر أقل {(1 - trend) * 100:.0f}% من نفس الفترة قبل 3 أشهر")
    if waste is not None and waste > max(WASTE_LIMIT, 1.5 * category_waste):
        notes.append(f"{waste * 100:.0f}% من كميته انرمت آخر أسبوعين "
                     f"(متوسط قسمه {category_waste * 100:.0f}%)")
    return (" و".join(notes) + ": راجع كميته أو مكانه في العرض") if notes else ""


def expected_surplus(batches, fc):
    """
    batches: list of (qty, days_left) on the shelf now. Old stock is sold first
    ("the old one goes to the front" - staff). Day by day we sell `fc` units,
    and whatever is left in a batch when its days run out is surplus.
    """
    batches = sorted([list(b) for b in batches if b[0] > 0], key=lambda b: b[1])
    surplus, day = 0.0, 0
    while batches:
        day += 1
        demand = fc
        for b in batches:                             # sell oldest first
            take = min(b[0], demand)
            b[0] -= take
            demand -= take
        surplus += sum(q for q, d in batches if d <= day)
        batches = [b for b in batches if b[1] > day and b[0] > 1e-9]
    return surplus


def surplus_alert(item_row, fc, batches):
    on_hand = sum(q for q, _ in batches)
    if on_hand <= 0:
        return ""
    surplus = expected_surplus(batches, fc)
    if surplus <= max(1, 0.1 * on_hand):
        return ""
    unit = UNIT_AR.get(item_row["unit"], item_row["unit"])
    n = round(surplus)
    amount = f"{n} {unit}" if item_row["unit"] == "kg" else ar_count(n, item_row["unit"])

    # each store chooses (optional column surplus_action in items.csv):
    #   markdown - the store CAN act on it today (discount, salad, juice, cut cups)
    #   reduce   - the store can't discount (chain rules / no outlet): prevent it instead
    #   none     - the store doesn't want this alert
    action = surplus_action(item_row)
    if action == "none":
        return ""
    if action == "markdown":
        if item_row["category"] == "produce":
            return (f"فائض متوقع {amount} قبل ما يخرب: وجّهه اليوم لركن السلطة أو العصير "
                    f"أو التقطيع في كاسات، أو صحون عرض")
        return f"فائض متوقع {amount} قبل ما ينتهي: خفّض سعره اليوم"
    return (f"فائض متوقع {amount} وما له تصريف: قلّلنا طلبية بكرة "
            f"(محسوب في التوصية)، ونبّه الإدارة بالكمية")


def surplus_action(item_row):
    """Store setting. Default if not set: produce -> markdown, bakery -> reduce."""
    action = item_row.get("surplus_action")
    if isinstance(action, str) and action.strip() in ("markdown", "reduce", "none"):
        return action.strip()
    return "markdown" if item_row["category"] == "produce" else "reduce"


# ---------------------------------------------------------------------------
# Turn the forecast into a recommendation + an Arabic reason
# ---------------------------------------------------------------------------
# Arabic counting: 1 كرتون, 2 كرتونين, 3-10 كراتين, 11+ كرتون
WORDS = {
    "carton": ("كرتون", "كرتونين", "كراتين"),
    "batch":  ("عجنة", "عجنتين", "عجنات"),
    "piece":  ("حبة", "حبتين", "حبات"),
    "bag":    ("كيس", "كيسين", "أكياس"),
}


def ar_count(n, key):
    one, two, many = WORDS[key]
    if n <= 0:
        return "ولا شي"
    if n == 1:
        return f"{one} واحدة" if key in ("batch", "piece") else f"{one} واحد"
    if n == 2:
        return two
    if 3 <= n <= 10:
        return f"{n} {many}"
    return f"{n} {one}"


def pack_key(item_row):
    if item_row["pack_size"] <= 1:
        return None
    return "carton" if item_row["category"] == "produce" else "batch"


def describe_qty(item_row, qty):
    """'3 كراتين (15 كجم)' / 'عجنتين (40 حبة)' / '9 حبات'"""
    pack = int(item_row["pack_size"])
    unit = UNIT_AR.get(item_row["unit"], item_row["unit"])
    key = pack_key(item_row)
    amount = f"{qty} {unit}" if item_row["unit"] == "kg" else ar_count(qty, item_row["unit"])
    return f"{ar_count(qty // pack, key)} ({amount})" if key else amount


def recommend(item_row, day, p, event, n_event_days, on_hand=0, min_qty=None):
    """p = the dict from plan_qty(). Returns the final quantity and the Arabic reason."""
    qty = p["order"]
    baseline, factor, source, cr = p["baseline"], p["factor"], p["source"], p["cr"]

    # optional display minimum ("the shelf should look full")
    display_note = ""
    if min_qty and qty < min_qty:
        extra = to_packs(min_qty, item_row["pack_size"]) - qty
        qty += extra
        display_note = f"رفعناها لحد العرض ({min_qty})، فائض متوقع ≈{extra}"

    unit = UNIT_AR.get(item_row["unit"], item_row["unit"])
    verb = "اطلب" if item_row["category"] == "produce" else "اخبز"
    what = describe_qty(item_row, qty)

    parts = [f"{WEEKDAY_AR[day.weekday()]}: متوسط آخر {WEEKS_BACK} أيام مثله {baseline:.0f} {unit}"]
    if event != "none":
        change = (factor - 1) * 100
        sign = "+" if change >= 0 else "−"
        if source == "learned":
            parts.append(f"{EVENT_AR[event]} {sign}{abs(change):.0f}% (من {n_event_days} يوم سابق)")
        elif source == "manual":
            parts.append(f"{EVENT_AR[event]} {sign}{abs(change):.0f}% (حدّده المدير)")
        else:
            parts.append(f"{EVENT_AR[event]}: ما فيه بيانات كافية، ما عدّلنا")

    if p.get("promo_factor", 1.0) != 1.0 or p.get("promo_source") == "not_enough_data":
        pf = p["promo_factor"]
        if p["promo_source"] == "learned":
            parts.append(f"عليه عرض بكرة +{(pf - 1) * 100:.0f}% (من {p['n_promo']} يوم عرض سابق)")
        else:
            parts.append("عليه عرض بكرة: ما فيه أيام عروض كافية، ما عدّلنا")

    # safety margin in plain words
    if item_row["shelf_life_days"] <= 1 and cr < SERVICE_MIN:
        parts.append(f"هامش أصغر لأن الباقي ينرمي آخر اليوم (مستوى خدمة {cr * 100:.0f}%)")
    elif cr >= 0.55:
        parts.append(f"هامش أمان عشان الرف ما يفضى (مستوى خدمة {cr * 100:.0f}%)")
    elif cr <= 0.45:
        parts.append("نقّصنا شوي لأن فائضه يخسّر أكثر من نقصه")
    if on_hand > 0:
        parts.append(f"خصمنا الموجود {on_hand:.0f} {unit}")
    if display_note:
        parts.append(display_note)

    if qty == 0:
        head = "لا تطلب بكرة" if item_row["category"] == "produce" else "لا تخبز بكرة"
    else:
        head = f"{verb} {what}"
    reason = f"{head}. السبب: " + " + ".join(parts) + "."
    tip = shelf_tip(item_row, on_hand, p["forecast"])
    if tip:
        reason += " " + tip
    return qty, reason


def shelf_tip(item_row, on_hand, fc):
    """
    What to do with yesterday's stock that is still good (staff: "the old one goes to the front").
    A small leftover in a store that can discount -> offer plate at a lower price, new stock in its place.
    Otherwise -> show yesterday's good stock in front of the new one.
    """
    if on_hand <= 0:
        return ""
    unit = UNIT_AR.get(item_row["unit"], item_row["unit"])
    amount = f"{on_hand:.0f} {unit}" if item_row["unit"] == "kg" else ar_count(round(on_hand), item_row["unit"])
    small = on_hand <= 0.25 * fc
    if small and surplus_action(item_row) == "markdown":
        return (f"الموجود من اليوم السابق ({amount}) صالح للمستهلك: "
                f"اعرضه في صحون بسعر أقل، وضع الجديد في مكانه.")
    return f"اعرض الموجود من اليوم السابق والصالح للمستهلك ({amount}) في المقدمة قبل الجديد."


# ---------------------------------------------------------------------------
# Run for all items
# ---------------------------------------------------------------------------
def run(folder, target=None):
    sales, items, calendar = load_data(folder)
    day = pd.Timestamp(target) if target else sales["date"].max() + pd.DateOffset(days=1)
    event, manual = event_on(calendar, day)
    data_source = "simulated" if "SIMULATED" in str(folder).upper() else "real"

    # optional stock file: what is on the shelf / in the back right now
    stock_file = Path(folder) / "stock.csv"
    # stock.csv: one row per item, or one row per batch (same item repeated)
    stock = pd.read_csv(stock_file) if stock_file.exists() else pd.DataFrame(columns=["item", "qty_on_hand", "days_left"])
    promos = load_promos(folder)

    rows = []
    for _, it in items.iterrows():
        hist = sales[(sales["item"] == it["item"]) & (sales["date"] < day)]
        mine = stock[stock["item"] == it["item"]]
        batches = list(zip(mine["qty_on_hand"].astype(float), mine["days_left"].astype(float)))
        on_hand = sum(q for q, _ in batches)
        usable = sum(q for q, d in batches if d >= 1)     # stock that still sells tomorrow

        p = plan_qty(hist, it, day, event, manual, on_hand=usable,
                     promo_today=(day, it["item"]) in promos)
        n_event = int((hist["event"] == event).sum()) if event != "none" else 0
        min_qty = it.get("min_qty")
        min_qty = None if pd.isna(min_qty) else int(min_qty)
        qty, reason = recommend(it, day, p, event, n_event, usable, min_qty)
        rows.append({
            "target_date": day.date(), "item": it["item"], "unit": it["unit"],
            "baseline_qty": round(p["baseline"], 1), "calendar_factor": round(p["factor"], 2),
            "forecast_qty": round(p["forecast"], 1),
            "critical_ratio": round(p["cr"], 2),
            "qty_on_hand": round(on_hand, 1),
            "recommended_qty": qty, "reason": reason,
            "alert": surplus_alert(it, p["forecast"], batches),
            "slow_mover": "",              # filled below (needs all items of the department)
            "data_source": data_source,
            "_category": it["category"],
            "_signals": slow_signals(hist),
        })

    # step 5: compare each item's waste with the usual waste of its department
    out = pd.DataFrame(rows)
    out["_waste"] = out["_signals"].str[1]
    dept_waste = out.groupby("_category")["_waste"].median()
    out["slow_mover"] = [
        slow_mover_note(t, w, dept_waste.get(c, 0) or 0)
        for (t, w), c in zip(out["_signals"], out["_category"])
    ]
    out = out.drop(columns=["_category", "_signals", "_waste"])
    (HERE / "output").mkdir(exist_ok=True)
    out.to_csv(HERE / "output" / "recommendations.csv", index=False, encoding="utf-8-sig")
    return out, day, event


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else HERE / "data" / "SIMULATED"
    target = sys.argv[2] if len(sys.argv) > 2 else None
    out, day, event = run(folder, target)
    print(f"target day: {day.date()} ({WEEKDAY_AR[day.weekday()]}), event: {event}\n")
    for r in out.itertuples():
        print(f"- {r.item}: {r.reason}")
        if r.alert:
            print(f"    ⚠ {r.alert}")
        if r.slow_mover:
            print(f"    🐢 {r.slow_mover}")
