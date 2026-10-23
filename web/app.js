// Mikyal static page: reads window.MIKYAL_DATA (made by engine/export_web.py).
// No numbers are made up here: everything shown comes from the engine's output files.
(function () {
  "use strict";

  const D = window.MIKYAL_DATA;
  if (!D) {
    document.querySelector("main").innerHTML =
      "<p class='card'>ما فيه بيانات. شغّل <code>python engine/export_web.py</code> أول.</p>";
    return;
  }

  const UNIT_AR = { kg: "كجم", piece: "حبة", bag: "كيس" };
  const PACK_AR = { produce: "الكرتون", bakery: "العجنة" };
  const CAT_AR = { produce: "خضار وفواكه", bakery: "مخبز" };
  const METHODS = ["mikyal", "store", "last_week", "avg_4wk"];
  const METHOD_AR = {
    mikyal: "مكيال", store: "طريقة المتجر الحالية",
    last_week: "نفس اليوم الأسبوع الماضي", avg_4wk: "متوسط آخر 4 أسابيع",
  };
  const EDIT_REASONS = ["عرض", "توريد متأخر", "حدث خاص", "تقدير المدير", "أخرى"];

  const rec = D.recommendations || [];
  const summary = D.backtest_summary || [];
  const trade = D.service_tradeoff || [];
  const bt = D.backtest || [];
  const items = Object.fromEntries((D.items || []).map((r) => [r.item, r]));

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const unitAr = (u) => UNIT_AR[u] || u;
  const num = (v, unit) => {
    const n = Number(v);
    if (!isFinite(n)) return "";
    return unit === "kg" ? (Math.round(n * 10) / 10).toString() : Math.round(n).toString();
  };
  // returns HTML: the number is isolated as LTR so "%" stays on the right side in RTL text
  const pct = (v) => (v === null || v === undefined || v === "" ? "–" : `<bdi dir="ltr">${Number(v).toFixed(1)}%</bdi>`);
  const parseDay = (s) => { const [y, m, d] = String(s).split("-").map(Number); return new Date(y, m - 1, d); };
  const catOf = (item) => (items[item] || {}).category;

  // ------------------------------------------------------------------ banner + tabs
  if ([...rec, ...summary].some((r) => r.data_source === "simulated")) $("#sim-banner").hidden = false;

  function showTab(name) {
    $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    $$(".tab").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
    if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  }
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  window.addEventListener("hashchange", () => showTabAndDraw(location.hash.slice(1)));

  // ------------------------------------------------------------------ TAB 1: order
  const target = rec.length ? parseDay(rec[0].target_date) : null;
  const final = Object.fromEntries(rec.map((r) => [r.item, { qty: r.recommended_qty, why: "" }]));
  let orderCat = "all";

  function fmtDate(d, cal) {
    try {
      return d.toLocaleDateString(`ar-SA-u-ca-${cal}-nu-latn`,
        { weekday: cal === "gregory" ? "long" : undefined, day: "numeric", month: "long", year: "numeric" });
    } catch (e) { return d.toISOString().slice(0, 10); }
  }

  if (target) {
    $("#order-title").textContent = `طلبية ${fmtDate(target, "gregory")}`;
    $("#order-sub").textContent = `${fmtDate(target, "islamic-umalqura")} · لكل صنف: الكمية + السبب`;
  }

  function renderAlerts() {
    const box = $("#alerts");
    const shown = rec.filter((r) => orderCat === "all" || catOf(r.item) === orderCat);
    const alerts = shown.filter((r) => r.alert).map((r) =>
      `<div class="alert-card">⚠ <b>${esc(r.item)}:</b>${esc(r.alert)}
        <span class="assume">اقتراح والقرار للمدير. التبرّع خيار بعد التحقق من اشتراطات سلامة الغذاء.</span></div>`);
    box.innerHTML = alerts.join("");
  }

  function steps(r) {
    const u = unitAr(r.unit);
    const it = items[r.item] || {};
    const base = Number(r.baseline_qty), cf = Number(r.calendar_factor), fc = Number(r.forecast_qty);
    const pf = base * cf > 0 ? fc / (base * cf) : 1;
    const out = [];
    out.push(["الأساس", `${num(base, r.unit)} ${u}`,
      "متوسط آخر 4 أيام مثل بكرة، بدون مناسبات ولا عروض"]);
    if (Math.abs(cf - 1) > 0.005) {
      out.push(["× عامل التقويم", `× ${cf.toFixed(2)}`, "مقدّر من بيانات الصنف نفسه في نفس المناسبة"]);
    }
    if (Math.abs(pf - 1) > 0.01) {
      out.push(["× عامل العرض", `× ${pf.toFixed(2)}`, "عليه عرض بكرة: مقدّر من أيام العروض السابقة"]);
    }
    out.push(["= التوقع", `${num(fc, r.unit)} ${u}`, "كم نتوقع ينباع بكرة"]);
    out.push(["+ هامش أمان", `مستوى خدمة ${Math.round(Number(r.critical_ratio) * 100)}%`,
      "عشان الرف ما يفضى، حسب تذبذب مبيعات الصنف (افتراض يعدّله المتجر)"]);
    if (Number(r.qty_on_hand) > 0) {
      out.push(["− الموجود الصالح", `${num(r.qty_on_hand, r.unit)} ${u}`, "من المخزون الحالي، يُباع أول"]);
    }
    const pack = Number(it.pack_size) > 1
      ? `مقرّبة لأعلى ${PACK_AR[it.category] || "للعبوة"} (${it.pack_size} ${u})` : "";
    out.push(["← الكمية المقترحة", `${num(r.recommended_qty, r.unit)} ${u}`, pack, true]);
    return out.map(([k, v, why, res]) =>
      `<li class="${res ? "result" : ""}"><span>${esc(k)}</span><span class="v">${esc(v)}</span>` +
      (why ? `<span class="why">${esc(why)}</span>` : "") + "</li>").join("");
  }

  function card(r) {
    const it = items[r.item] || {};
    const u = unitAr(r.unit);
    const f = final[r.item];
    const edited = Number(f.qty) !== Number(r.recommended_qty);
    const meta = [CAT_AR[it.category], it.shelf_life_days ? `صلاحية ${it.shelf_life_days} ${it.shelf_life_days > 2 ? "أيام" : it.shelf_life_days == 2 ? "يومين" : "يوم"}` : "",
      Number(it.pack_size) > 1 ? `${PACK_AR[it.category] || "العبوة"} ${it.pack_size} ${u}` : ""].filter(Boolean).join(" · ");
    const zero = Number(r.recommended_qty) === 0;
    return `
    <article class="item-card ${edited ? "edited" : ""} ${r.alert ? "has-alert" : ""}" data-item="${esc(r.item)}">
      <div class="item-row">
        <div>
          <div class="item-name">${esc(r.item)}</div>
          <div class="item-meta">${esc(meta)}</div>
          <div class="headline ${zero ? "zero" : ""}">${esc(r.reason_head)}</div>
          ${r.slow_mover ? `<div class="slow-note">🐢 ${esc(r.slow_mover)}</div>` : ""}
        </div>
        <div class="final">
          <label>الكمية النهائية (${esc(u)})</label>
          <div class="qty-box">
            <button type="button" data-step="-1" aria-label="أقل">−</button>
            <input type="text" dir="ltr" inputmode="decimal" value="${esc(f.qty)}" aria-label="الكمية النهائية ${esc(r.item)}">
            <button type="button" data-step="1" aria-label="أكثر">+</button>
          </div>
          ${edited ? `<select class="edit-reason" aria-label="سبب التعديل">
            <option value="">سبب التعديل…</option>
            ${EDIT_REASONS.map((x) => `<option ${f.why === x ? "selected" : ""}>${x}</option>`).join("")}
          </select>` : ""}
        </div>
      </div>
      <details>
        <summary>ليش هالرقم؟</summary>
        <ol class="steps">${steps(r)}</ol>
        ${(r.reason_parts || []).length ? `<ul class="reason-list">${r.reason_parts.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}
        ${r.reason_tip ? `<div class="tip">💡 ${esc(r.reason_tip)}</div>` : ""}
      </details>
    </article>`;
  }

  // promo factor = forecast / (baseline × calendar), same as in steps()
  const promoOf = (r) => {
    const b = Number(r.baseline_qty) * Number(r.calendar_factor);
    return b > 0 ? Number(r.forecast_qty) / b : 1;
  };

  function renderSummary() {
    const shown = rec.filter((r) => orderCat === "all" || catOf(r.item) === orderCat);
    const ordered = shown.filter((r) => Number(final[r.item].qty) > 0).length;
    const promo = shown.filter((r) => promoOf(r) > 1.01).length;
    const onHand = shown.filter((r) => Number(r.qty_on_hand) > 0).length;
    const alerts = shown.filter((r) => r.alert).length;
    const tile = (n, label, cls = "") => `<div class="sum-tile ${cls}"><b>${n}</b><span>${label}</span></div>`;
    $("#order-summary").innerHTML =
      tile(`${ordered} من ${shown.length}`, "أصناف نطلبها") +
      tile(promo, "عليها عرض بكرة") +
      tile(onHand, "فيها موجود من أمس") +
      tile(alerts, "تنبيه فائض", alerts ? "warn" : "");
  }

  function renderOrder() {
    renderSummary();
    const open = new Set($$("#order-list details[open]").map((d) => d.closest(".item-card").dataset.item));
    const shown = rec.filter((r) => orderCat === "all" || catOf(r.item) === orderCat);
    $("#order-list").innerHTML = shown.map(card).join("");
    $$("#order-list .item-card").forEach((c) => { if (open.has(c.dataset.item)) $("details", c).open = true; });
    renderAlerts();
  }

  $("#order-list").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-step]");
    if (!b) return;
    const name = b.closest(".item-card").dataset.item;
    const step = Math.max(Number((items[name] || {}).pack_size) || 1, 1);
    final[name].qty = Math.max(0, Number(final[name].qty) + step * Number(b.dataset.step));
    renderOrder();
  });
  $("#order-list").addEventListener("change", (e) => {
    const c = e.target.closest(".item-card");
    if (!c) return;
    const f = final[c.dataset.item];
    if (e.target.matches("input")) {
      // accept Arabic-Indic digits too (٣٦ -> 36)
      const v = e.target.value.replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d)).replace("٫", ".");
      f.qty = Math.max(0, Number(v) || 0);
    }
    if (e.target.matches("select")) f.why = e.target.value;
    renderOrder();
  });
  $$("#order-filter button").forEach((b) => b.addEventListener("click", () => {
    orderCat = b.dataset.cat;
    $$("#order-filter button").forEach((x) => x.classList.toggle("on", x === b));
    renderOrder();
  }));

  function describe(item, qty) {
    const it = items[item] || {};
    const r = rec.find((x) => x.item === item);
    const u = unitAr(r.unit);
    const pack = Number(it.pack_size);
    return pack > 1 && qty % pack === 0
      ? `${num(qty, r.unit)} ${u} (${qty / pack} × ${PACK_AR[it.category] || "عبوة"} ${pack})`
      : `${num(qty, r.unit)} ${u}`;
  }

  $("#copy-order").addEventListener("click", async () => {
    const day = target ? fmtDate(target, "gregory") : "";
    const lines = rec.filter((r) => Number(final[r.item].qty) > 0)
      .map((r) => `- ${r.item}: ${describe(r.item, Number(final[r.item].qty))}`);
    const text = `طلبية ${day}\n${lines.join("\n")}`;
    try { await navigator.clipboard.writeText(text); } catch (e) {
      const t = document.createElement("textarea");
      t.value = text; document.body.appendChild(t); t.select();
      try { document.execCommand("copy"); } catch (e2) { /* ignore */ }
      t.remove();
    }
    $("#copy-done").hidden = false;
    setTimeout(() => { $("#copy-done").hidden = true; }, 2000);
  });

  $("#download-order").addEventListener("click", () => {
    const q = (s) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const head = ["target_date", "item", "unit", "recommended_qty", "final_qty", "edit_reason"];
    const rows = rec.map((r) => [r.target_date, r.item, r.unit, r.recommended_qty,
      final[r.item].qty, Number(final[r.item].qty) !== Number(r.recommended_qty) ? final[r.item].why : ""]);
    const csv = "﻿" + [head, ...rows].map((row) => row.map(q).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `mikyal-order-${rec[0] ? rec[0].target_date : "today"}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
  });

  // ------------------------------------------------------------------ TAB: worker tasks
  // Few, one-line tasks per shift (staff told us long lists get skipped).
  let shift = "am";
  const done = {};   // "produce-am" -> Set of finished task ids
  const decision = {};   // surplus item -> manager's choice
  const SURPLUS_OPTS = ["سعر أقل (لو المتجر يسمح)", "منصة بيع الفائض", "لا شي"];

  // worker wording: "6 كراتين" / "3 عجنات" instead of the full kg breakdown
  const PACK_N = { produce: ["كرتون", "كرتونين", "كراتين"], bakery: ["عجنة", "عجنتين", "عجنات"] };
  function shortQty(r) {
    const it = items[r.item] || {}, q = Number(final[r.item].qty), p = Number(it.pack_size);
    const w = PACK_N[it.category];
    if (!(p > 1 && q % p === 0 && w)) return `${num(q, r.unit)} ${unitAr(r.unit)}`;
    const n = q / p;
    return n === 1 ? w[0] : n === 2 ? w[1] : `${n} ${n <= 10 ? w[2] : w[0]}`;
  }

  // produce and bakery have different workers, so each gets its own list
  let dept = "produce";
  const DEPT_AR = { produce: "الخضار", bakery: "المخبز" };

  function shiftTasks(d, s) {
    const mine = rec.filter((r) => catOf(r.item) === d);
    const ordered = mine.filter((r) => Number(final[r.item].qty) > 0).map((r) => `${r.item} ${shortQty(r)}`).join("، ");
    const onHand = mine.filter((r) => Number(r.qty_on_hand) > 0).map((r) => r.item).join("، ");
    const surplus = mine.filter((r) => r.alert).slice(0, 1)
      .map((r) => [`sur-${r.item}`, `${r.item}: متوقع يبقى منه، بلّغ المدير`, ""]);
    if (s === "am") {
      return [
        d === "produce" ? ["recv", "استلم طلبية الخضار", ordered] : ["bake", "اخبز حسب الطلبية", ordered],
        ...(onHand ? [["front", "الصالح من أمس قدّام، والجديد ورا", onHand]] : []),
        d === "produce" ? ["damaged", "شيل الحبات التالفة من الرف", ""] : ["expired", "شيل اللي انتهت صلاحيته من الرف", ""],
        ...surplus,
      ];
    }
    return [
      d === "produce" ? ["refill", "عبّي الناقص من المستودع قبل الذروة", ""] : ["refill", "عبّي الرف من المخبوزات الجاهزة قبل الذروة", ""],
      ["damaged-pm", d === "produce" ? "شيل الحبات التالفة من الرف" : "شيل اللي انتهت صلاحيته من الرف", ""],
      ["count", "سجّل الباقي آخر الشفت", "يدخل في حساب طلبية بكرة"],
    ];
  }
  const doneSet = (d, s) => (done[`${d}-${s}`] ||= new Set());

  function renderTasks() {
    const list = shiftTasks(dept, shift), set = doneSet(dept, shift);
    $("#task-list").innerHTML = list.map(([id, title, sub]) => `
      <label class="task ${set.has(id) ? "done" : ""}">
        <input type="checkbox" data-id="${esc(id)}" ${set.has(id) ? "checked" : ""}>
        <span><b>${esc(title)}</b>${sub ? `<span class="sub">${esc(sub)}</span>` : ""}</span>
      </label>`).join("");
    $("#task-progress").innerHTML = ["produce", "bakery"].flatMap((d) => ["am", "pm"].map((s) => {
      const t = shiftTasks(d, s), k = t.filter(([id]) => doneSet(d, s).has(id)).length;
      return `<div class="prog"><div class="prog-head"><span>${DEPT_AR[d]} · ${s === "am" ? "الصباحي" : "المسائي"}</span>
        <b>${k} من ${t.length} تمت</b></div><div class="prog-bar"><div style="width:${t.length ? (k / t.length) * 100 : 0}%"></div></div></div>`;
    })).join("");
    const surplus = rec.filter((r) => r.alert);
    $("#surplus-box").innerHTML = surplus.length ? surplus.map((r) => `
      <div class="alert-card"><b>${esc(r.item)}:</b>${esc(r.alert)}
        <select class="sur-pick" data-item="${esc(r.item)}" aria-label="قرار الفائض ${esc(r.item)}">
          <option value="">قرار المدير…</option>
          ${SURPLUS_OPTS.map((o) => `<option ${decision[r.item] === o ? "selected" : ""}>${o}</option>`).join("")}
        </select></div>`).join("")
      : `<p class="muted small">✓ ما فيه فائض متوقع في طلبية بكرة.</p>`;
  }

  $("#task-list").addEventListener("change", (e) => {
    const id = e.target.dataset.id;
    if (!id) return;
    const set = doneSet(dept, shift);
    e.target.checked ? set.add(id) : set.delete(id);
    renderTasks();
  });
  $("#surplus-box").addEventListener("change", (e) => {
    if (e.target.matches(".sur-pick")) decision[e.target.dataset.item] = e.target.value;
  });
  $$("#shift-pick button").forEach((b) => b.addEventListener("click", () => {
    shift = b.dataset.shift;
    $$("#shift-pick button").forEach((x) => x.classList.toggle("on", x === b));
    renderTasks();
  }));
  $$("#dept-pick button").forEach((b) => b.addEventListener("click", () => {
    dept = b.dataset.dept;
    $$("#dept-pick button").forEach((x) => x.classList.toggle("on", x === b));
    renderTasks();
  }));

  // ------------------------------------------------------------------ TAB 2: backtest
  let group = "ALL";
  const row = (item, m) => summary.find((r) => r.item === item && r.method === m) || {};
  const nDays = Math.max(0, ...summary.map((r) => Number(r.n_days) || 0));
  $("#compare-sub").textContent =
    `${nDays} يوم اختبار (آخر 8 أسابيع + رمضان 2026) · الطلب الحقيقي من المحاكاة`;

  function renderStats() {
    const m = row(group, "mikyal"), s = row(group, "store");
    const src = m.data_source === "simulated" ? "محاكاة" : esc(m.data_source || "");
    const tile = (label, a, b) => `
      <div class="stat">
        <div class="label">${label}</div>
        <div class="big">${pct(a)}</div>
        <div class="vs">طريقة المتجر الحالية: <b>${pct(b)}</b></div>
        <span class="tag">${src} · موزون بالتكلفة</span>
      </div>`;
    $("#stats").innerHTML = tile("الهدر مع مكيال", m.waste_pct, s.waste_pct) +
      tile("الرف الفاضي مع مكيال", m.lost_pct, s.lost_pct);
  }

  function renderBars() {
    const rows = METHODS.map((m) => ({ m, ...row(group, m) }));
    const top = Math.max(1, ...rows.flatMap((r) => [Number(r.waste_pct) || 0, Number(r.lost_pct) || 0]));
    $("#method-bars").innerHTML = rows.map((r) => `
      <div class="m-row ${r.m === "mikyal" ? "me" : ""}">
        <div class="lbl">${METHOD_AR[r.m]}</div>
        <div class="bar-line"><div class="bar waste" style="width:${(Number(r.waste_pct) / top) * 75}%"></div>هدر ${pct(r.waste_pct)}</div>
        <div class="bar-line"><div class="bar lost" style="width:${(Number(r.lost_pct) / top) * 75}%"></div>رف فاضي ${pct(r.lost_pct)}</div>
      </div>`).join("");
  }

  function renderItemTable() {
    const cat = group.startsWith("ALL:") ? group.slice(4) : null;
    const names = [...new Set(summary.map((r) => r.item))]
      .filter((n) => !n.startsWith("ALL") && (!cat || catOf(n) === cat));
    const cell = (a, b) => {
      const cls = Number(a) <= Number(b) ? "good" : "bad";
      return `<td class="num ${cls}">${esc(a)}</td><td class="num">${esc(b)}</td>`;
    };
    $("#item-table").innerHTML = `
      <thead><tr><th>الصنف</th><th>الوحدة</th><th>هدر مكيال</th><th>هدر المتجر</th><th>رف فاضي مكيال</th><th>رف فاضي المتجر</th></tr></thead>
      <tbody>${names.map((n) => {
        const m = row(n, "mikyal"), s = row(n, "store");
        const unit = (items[n] || {}).unit || (rec.find((r) => r.item === n) || {}).unit;
        return `<tr><td>${esc(n)}</td><td>${esc(unitAr(unit))}</td>${cell(m.waste_qty, s.waste_qty)}${cell(m.lost_qty, s.lost_qty)}</tr>`;
      }).join("")}</tbody>`;
  }

  function renderWape() {
    const rows = ["mikyal", "last_week", "avg_4wk"].map((m) => [METHOD_AR[m], row(group, m).wape, m === "mikyal"]);
    $("#wape").innerHTML = `<table class="grid"><tbody>${rows.map(([n, w, me]) =>
      `<tr class="${me ? "hl" : ""}"><td>${n}</td><td class="num">${pct(w)}</td></tr>`).join("")}
      <tr><td class="muted">${METHOD_AR.store} <span class="small">(خطأ طلبيتها، مو توقع)</span></td>
        <td class="num muted">${pct(row(group, "store").wape)}</td></tr></tbody></table>
      <p class="muted small">متوسط الفرق بين التوقع والطلب الحقيقي، كنسبة من الطلب. الأقل أدق.</p>`;
  }

  $$("#compare-group button").forEach((b) => b.addEventListener("click", () => {
    group = b.dataset.group;
    $$("#compare-group button").forEach((x) => x.classList.toggle("on", x === b));
    renderCompare();
  }));

  // line chart: actual vs forecasts, per item and test window
  const btItems = [...new Set(bt.map((r) => r.item))];
  function windowsOf(item) {
    const rows = bt.filter((r) => r.item === item).sort((a, b) => (a.date < b.date ? -1 : 1));
    const wins = [];
    rows.forEach((r, i) => {
      const gap = i > 0 && (parseDay(r.date) - parseDay(rows[i - 1].date)) / 864e5 > 1;
      if (i === 0 || gap) wins.push([]);
      wins[wins.length - 1].push(r);
    });
    return wins;
  }
  const winLabel = (w) => (w.some((r) => r.event === "ramadan") ? "رمضان 2026" : "آخر 8 أسابيع");

  $("#chart-item").innerHTML = btItems.map((n) => `<option>${esc(n)}</option>`).join("");
  function fillWindows() {
    const wins = windowsOf($("#chart-item").value);
    const keep = $("#chart-window").value;
    $("#chart-window").innerHTML = wins.map((w, i) => `<option value="${i}">${winLabel(w)}</option>`).join("");
    if (keep && keep < wins.length) $("#chart-window").value = keep;
  }
  $("#chart-item").addEventListener("change", () => { fillWindows(); renderLine(); });
  $("#chart-window").addEventListener("change", renderLine);

  // chart width follows the screen, so the 11px labels stay readable on a phone
  const chartW = (el) => Math.max(320, Math.min(640, el.clientWidth || 640));

  function niceMax(v) {
    const p = Math.pow(10, Math.floor(Math.log10(v || 1)));
    return [1, 2, 2.5, 5, 10].map((k) => k * p).find((k) => k >= v) || v;
  }

  // last 14 days only: actual demand as grey columns, Mikyal's forecast as one line on top
  function renderLine() {
    const item = $("#chart-item").value;
    const w = (windowsOf(item)[Number($("#chart-window").value) || 0] || []).slice(-14);
    if (!w.length) { $("#line-chart").innerHTML = ""; return; }
    const W = chartW($("#line-chart")), H = 260, L = 40, R = 12, T = 12, B = 30;
    const ymax = niceMax(Math.max(...w.flatMap((r) => [Number(r.actual) || 0, Number(r.pred_mikyal) || 0])) * 1.05);
    const step = (W - L - R) / w.length;
    const x = (i) => L + step * (i + 0.5);
    const y = (v) => T + (1 - v / ymax) * (H - T - B);
    let g = "";
    w.forEach((r, i) => {
      if (r.event === "ramadan") g += `<rect x="${L + step * i}" y="${T}" width="${step}" height="${H - T - B}" fill="var(--shade)"/>`;
      else if (Number(r.promo) === 1) g += `<rect x="${L + step * i}" y="${T}" width="${step}" height="${H - T - B}" fill="var(--promo)"/>`;
    });
    for (let k = 0; k <= 4; k++) {
      const v = (ymax * k) / 4;
      g += `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>` +
        `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${num(v, "kg")}</text>`;
    }
    const bw = step * 0.6;
    w.forEach((r, i) => {
      const v = Number(r.actual) || 0;
      g += `<rect x="${x(i) - bw / 2}" y="${y(v)}" width="${bw}" height="${y(0) - y(v)}" rx="2" fill="var(--gray2)"/>`;
      if (i % 2 === 0) {
        const d = parseDay(r.date);
        g += `<text x="${x(i)}" y="${H - 10}" text-anchor="middle">${d.getDate()}/${d.getMonth() + 1}</text>`;
      }
    });
    const pts = w.map((r, i) => `${x(i).toFixed(1)},${y(Number(r.pred_mikyal) || 0).toFixed(1)}`).join(" ");
    g += `<polyline points="${pts}" fill="none" stroke="var(--mikyal)" stroke-width="2.5" stroke-linejoin="round"/>`;
    g += w.map((r, i) => `<circle cx="${x(i)}" cy="${y(Number(r.pred_mikyal) || 0)}" r="3.5" fill="var(--mikyal)"/>`).join("");
    const unit = unitAr((w[0] || {}).unit);
    $("#line-chart").innerHTML =
      `<svg class="chart" viewBox="0 0 ${W} ${H}" direction="ltr" role="img" aria-label="الطلب الحقيقي مقابل توقع مكيال (${esc(unit)})">${g}</svg>`;
    $("#line-legend").innerHTML =
      `<span><i class="bar-key"></i>الطلب الحقيقي</span><span><i class="mikyal"></i>توقع مكيال</span>` +
      (w.some((r) => r.event === "ramadan") ? `<span><i class="shade-r"></i>رمضان</span>` : "") +
      (w.some((r) => Number(r.promo) === 1) ? `<span><i class="shade-p"></i>يوم عرض</span>` : "") +
      `<span>آخر ${w.length} يوم · الوحدة: ${esc(unit)}</span>`;
  }

  function renderCompare() { renderStats(); renderBars(); renderItemTable(); renderWape(); }

  // ------------------------------------------------------------------ TAB 3: trade-off
  function renderTradeoff() {
    if (!trade.length) { $("#tradeoff-chart").innerHTML = "<p class='muted'>ما فيه ملف service_tradeoff.csv</p>"; return; }
    const W = chartW($("#tradeoff-chart")), H = 300, L = 46, R = 16, T = 16, B = 40;
    const xmax = niceMax(Math.max(...trade.map((t) => Math.max(t.store_waste_pct, t.mikyal_waste_pct))) * 1.08);
    const ymax = niceMax(Math.max(...trade.map((t) => Math.max(t.store_lost_pct, t.mikyal_lost_pct))) * 1.2);
    const x = (v) => L + (v / xmax) * (W - L - R);
    const y = (v) => T + (1 - v / ymax) * (H - T - B);
    let g = "";
    for (let k = 0; k <= 4; k++) {
      const vx = (xmax * k) / 4, vy = (ymax * k) / 4;
      g += `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${y(vy)}" y2="${y(vy)}"/>` +
        `<text x="${L - 6}" y="${y(vy) + 4}" text-anchor="end">${vy.toFixed(1)}%</text>` +
        `<text x="${x(vx)}" y="${H - B + 16}" text-anchor="middle">${vx.toFixed(1)}%</text>`;
    }
    g += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">الهدر (% من الطلب، موزون بالتكلفة)</text>`;
    g += `<text x="12" y="${(T + H - B) / 2}" text-anchor="middle" transform="rotate(-90 12 ${(T + H - B) / 2})">الرف الفاضي %</text>`;
    const pts = trade.map((t) => `${x(t.mikyal_waste_pct).toFixed(1)},${y(t.mikyal_lost_pct).toFixed(1)}`).join(" ");
    g += `<polyline points="${pts}" fill="none" stroke="var(--mikyal)" stroke-width="2"/>`;
    // the points sit close together: label only the lowest level and the default (rest in the table)
    g += trade.map((t, i) => {
      const def = Math.abs(t.service_level - 0.97) < 1e-6;
      const label = def ? `${Math.round(t.service_level * 100)}% الافتراضي`
        : i === 0 ? `${Math.round(t.service_level * 100)}%` : "";
      return `<circle cx="${x(t.mikyal_waste_pct)}" cy="${y(t.mikyal_lost_pct)}" r="${def ? 6 : 4}" fill="var(--mikyal)"/>` +
        (label ? `<text x="${x(t.mikyal_waste_pct) + 9}" y="${y(t.mikyal_lost_pct) + 4}" style="${def ? "font-weight:700;fill:var(--ink)" : ""}">${label}</text>` : "");
    }).join("");
    const s = trade[0];
    g += `<circle cx="${x(s.store_waste_pct)}" cy="${y(s.store_lost_pct)}" r="7" fill="var(--store)"/>` +
      `<text x="${x(s.store_waste_pct) + 8}" y="${y(s.store_lost_pct) + 22}" text-anchor="end" style="fill:var(--ink)">طريقة المتجر الحالية</text>`;
    $("#tradeoff-chart").innerHTML =
      `<svg class="chart" viewBox="0 0 ${W} ${H}" direction="ltr" role="img" aria-label="الهدر مقابل الرف الفاضي">${g}</svg>`;

    $("#tradeoff-table").innerHTML = `
      <thead><tr><th>مستوى الخدمة</th><th>هدر مكيال</th><th>رف فاضي مكيال</th><th>هدر المتجر</th><th>رف فاضي المتجر</th></tr></thead>
      <tbody>${trade.map((t) => `<tr class="${Math.abs(t.service_level - 0.97) < 1e-6 ? "hl" : ""}">
        <td>${Math.round(t.service_level * 100)}%</td><td class="num">${pct(t.mikyal_waste_pct)}</td>
        <td class="num">${pct(t.mikyal_lost_pct)}</td><td class="num">${pct(t.store_waste_pct)}</td>
        <td class="num">${pct(t.store_lost_pct)}</td></tr>`).join("")}</tbody>`;
  }

  // ------------------------------------------------------------------ start
  renderOrder();
  renderCompare();
  fillWindows();
  renderLine();
  renderTradeoff();
  function showTabAndDraw(name) { showTab(name); renderLine(); renderTradeoff(); renderTasks(); }   // hidden tabs have no width
  showTabAndDraw(["order", "tasks", "compare", "balance"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "order");
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => { renderLine(); renderTradeoff(); renderTasks(); }));
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { renderLine(); renderTradeoff(); }, 150);
  });
})();
