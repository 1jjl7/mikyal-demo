"""
report.py - a BACKUP demo page made only from the engine's output files.

Why: if the real UI is not ready or the demo laptop has a problem, we can still
show Mikyal working. One self-contained HTML file: opens in any browser, no installs.

Run (after mikyal.py and backtest.py --tradeoff):
    python report.py
Out:
    output/report.html
"""

import html
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "output"
METHOD_AR = {"mikyal": "مكيال", "store": "طريقة المتجر الحالية",
             "last_week": "نفس اليوم الأسبوع الماضي", "avg_4wk": "متوسط آخر 4 أسابيع"}


def esc(x):
    return "" if pd.isna(x) else html.escape(str(x))


def recommendations_table(rec):
    rows = []
    for r in rec.itertuples():
        alert = f'<div class="alert">⚠ {esc(r.alert)}</div>' if esc(r.alert) else ""
        slow = f'<div class="slow">🐢 {esc(r.slow_mover)}</div>' if esc(r.slow_mover) else ""
        head, _, why = esc(r.reason).partition(". السبب: ")
        rows.append(f"<tr><td class='item'>{esc(r.item)}</td>"
                    f"<td><div class='head'>{head}</div><div class='why'>السبب: {why}</div>{alert}{slow}</td></tr>")
    return "<table class='rec'>" + "".join(rows) + "</table>"


def comparison_bars(summary):
    a = summary[summary["item"] == "ALL"].set_index("method")
    biggest = max(a["waste_pct"].max(), a["lost_pct"].max(), 1)
    rows = []
    for m in ["mikyal", "store", "last_week", "avg_4wk"]:
        w, l = a.loc[m, "waste_pct"], a.loc[m, "lost_pct"]
        cls = " me" if m == "mikyal" else ""
        rows.append(
            f"<div class='bar-row{cls}'><div class='lbl'>{METHOD_AR[m]}</div>"
            f"<div class='bars'><div class='bar waste' style='width:{w / biggest * 100:.0f}%'></div>"
            f"<span>هدر {w}%</span></div>"
            f"<div class='bars'><div class='bar lost' style='width:{l / biggest * 100:.0f}%'></div>"
            f"<span>رف فاضي {l}%</span></div></div>")
    return "".join(rows)


def tradeoff_svg(t):
    """Waste (x) vs empty shelf (y). Mikyal's line for each service level + the store's point."""
    W, H, P = 520, 300, 46
    xmax = max(t["store_waste_pct"].max(), t["mikyal_waste_pct"].max()) * 1.15
    ymax = max(t["store_lost_pct"].max(), t["mikyal_lost_pct"].max()) * 1.25
    x = lambda v: P + v / xmax * (W - 2 * P)
    y = lambda v: H - P - v / ymax * (H - 2 * P)
    pts = " ".join(f"{x(a):.1f},{y(b):.1f}" for a, b in zip(t["mikyal_waste_pct"], t["mikyal_lost_pct"]))
    dots = "".join(
        f"<circle cx='{x(a):.1f}' cy='{y(b):.1f}' r='4' class='m'/>"
        f"<text x='{x(a) + 6:.1f}' y='{y(b) - 6:.1f}' class='t'>{lvl * 100:.0f}%</text>"
        for a, b, lvl in zip(t["mikyal_waste_pct"], t["mikyal_lost_pct"], t["service_level"]))
    sx, sy = x(t["store_waste_pct"].iloc[0]), y(t["store_lost_pct"].iloc[0])
    return f"""
<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="الهدر مقابل الرف الفاضي">
  <line x1="{P}" y1="{H - P}" x2="{W - P}" y2="{H - P}" class="axis"/>
  <line x1="{P}" y1="{P}" x2="{P}" y2="{H - P}" class="axis"/>
  <text x="{W / 2}" y="{H - 10}" class="t" text-anchor="middle">الهدر (% من الطلب) ←</text>
  <text x="14" y="{H / 2}" class="t" transform="rotate(-90 14 {H / 2})" text-anchor="middle">الرف الفاضي (%) ←</text>
  <polyline points="{pts}" class="mline"/>{dots}
  <circle cx="{sx:.1f}" cy="{sy:.1f}" r="7" class="s"/>
  <text x="{sx - 10:.1f}" y="{sy - 12:.1f}" class="t" text-anchor="end">طريقة المتجر الحالية</text>
</svg>"""


def main():
    rec = pd.read_csv(OUT / "recommendations.csv")
    summary = pd.read_csv(OUT / "backtest_summary.csv")
    trade = pd.read_csv(OUT / "service_tradeoff.csv") if (OUT / "service_tradeoff.csv").exists() else None
    simulated = (rec["data_source"] == "simulated").any()
    day = esc(rec["target_date"].iloc[0])
    n_days = int(summary["n_days"].max())

    banner = ("<div class='banner'>⚠ بيانات محاكاة مبنية على 3 زيارات ميدانية، مو بيانات متجر حقيقية</div>"
              if simulated else "")
    trade_html = (f"<h2>المتجر يختار التوازن (مستوى الخدمة)</h2>{tradeoff_svg(trade)}"
                  f"<p class='note'>كل نقطة زرقاء = مكيال بمستوى خدمة مختلف. كل ما زاد المستوى، يقل الرف الفاضي ويزيد الهدر شوي.</p>"
                  if trade is not None else "")

    # for the slide: a few items that show a promo, a reason and alerts
    show = ["جزر", "فلفل بارد", "صامولي", "صامولي حليب", "خبز مصري"]
    rec_slide = rec[rec["item"].isin(show)] if rec["item"].isin(show).any() else rec.head(5)
    sections = {
        "rec": f"<h2>توصيات يوم {day} (يوم عروض)</h2>{banner}<div class='card'>{recommendations_table(rec_slide)}</div>",
        "compare": (f"<h2>الاختبار العكسي ({n_days} يوم): الهدر والرف الفاضي</h2>{banner}"
                    f"<div class='card'>{comparison_bars(summary)}</div>{trade_html}"),
    }
    page = f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>مكيال: توصيات بكرة</title>
<style>
  :root {{ --bg:#f6f8f7; --card:#fff; --ink:#0f2e2c; --muted:#5b6b69; --line:#dde5e3;
          --green:#1f9d6b; --amber:#e99a1c; --red:#d4483b; --blue:#2f6fb3; --soft:#e9f4ef; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:16px; background:var(--bg); color:var(--ink);
         font-family:"Noto Naskh Arabic","Segoe UI",Tahoma,sans-serif; line-height:1.7; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  h1 {{ margin:0; font-size:1.6rem; }} h2 {{ font-size:1.15rem; margin:22px 0 8px; }}
  .sub {{ color:var(--muted); }}
  .banner {{ background:#fff3d6; border:1px solid var(--amber); border-radius:10px; padding:8px 12px; margin:10px 0; font-weight:700; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px; }}
  table.rec {{ width:100%; border-collapse:collapse; }}
  table.rec td {{ border-bottom:1px solid var(--line); padding:10px 8px; vertical-align:top; }}
  td.item {{ font-weight:700; width:120px; white-space:nowrap; }}
  .head {{ font-weight:700; font-size:1.05rem; }} .why {{ color:var(--muted); font-size:.92rem; }}
  .alert {{ margin-top:4px; background:#fff3d6; border-radius:8px; padding:4px 8px; font-size:.9rem; }}
  .slow {{ margin-top:4px; background:#eef2fb; border-radius:8px; padding:4px 8px; font-size:.9rem; }}
  .bar-row {{ display:grid; grid-template-columns:170px 1fr 1fr; gap:8px; align-items:center; padding:6px 0; border-bottom:1px dashed var(--line); }}
  .bar-row.me .lbl {{ font-weight:700; color:var(--green); }}
  .bars {{ display:flex; align-items:center; gap:6px; font-size:.85rem; }}
  .bar {{ height:14px; border-radius:7px; min-width:3px; }}
  .bar.waste {{ background:var(--red); }} .bar.lost {{ background:var(--amber); }}
  .chart {{ width:100%; max-width:560px; background:var(--card); border:1px solid var(--line); border-radius:14px; }}
  .axis {{ stroke:#9fb1ae; }} .mline {{ fill:none; stroke:var(--blue); stroke-width:2; }}
  circle.m {{ fill:var(--blue); }} circle.s {{ fill:var(--red); }}
  .t {{ font-size:11px; fill:var(--ink); }}
  .note {{ color:var(--muted); font-size:.85rem; }}
  @media (max-width:600px) {{ .bar-row {{ grid-template-columns:1fr; }} td.item {{ width:auto; }} }}
</style></head><body><div class="wrap">
  <h1>مكيال 🧺</h1>
  <div class="sub">توصيات يوم {day} · لكل صنف: الكمية + السبب + التنبيه</div>
  {banner}
  <h2>توصيات بكرة</h2>
  <div class="card">{recommendations_table(rec)}</div>
  <h2>الاختبار العكسي ({n_days} يوم): الهدر والرف الفاضي</h2>
  <div class="card">{comparison_bars(summary)}</div>
  <p class="note">كل طريقة تدير رفها: تطلب كل صباح بالبيانات اللي قبل اليوم بس، والقديم ينباع أول، واللي يخرب ينحسب هدر. النسب موزونة بتكلفة كل صنف عشان ما نجمع كيلو مع حبة.</p>
  {trade_html}
</div></body></html>"""
    (OUT / "report.html").write_text(page, encoding="utf-8")
    print(f"saved {OUT / 'report.html'}")

    # small pages, one section each -> screenshots for the slides
    style = page[page.index("<style>"):page.index("</style>") + 8]
    for name, body in sections.items():
        wide = "<style>.wrap{max-width:1500px}</style>" if name == "rec" else ""
        snap = (f"<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>{style}{wide}</head>"
                f"<body><div class='wrap'>{body}</div></body></html>")
        (OUT / f"snap_{name}.html").write_text(snap, encoding="utf-8")


if __name__ == "__main__":
    main()
