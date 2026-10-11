"use strict";
const $ = (s, el=document) => el.querySelector(s);
const pct = (x, d=1) => x == null ? "–" : (100*x).toFixed(d) + "%";
const num = (x, d=0) => x == null ? "–" : Number(x).toLocaleString(undefined, {maximumFractionDigits:d, minimumFractionDigits:d});
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const cache = {};
async function get(name){ if(!cache[name]){ const r = await fetch("/ui/"+name); if(!r.ok) throw new Error(name+" "+r.status); cache[name] = await r.json(); } return cache[name]; }
function css(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

// ---------------------------------------------------------------- tabs
function showTab(tab){
  document.querySelectorAll("#mainnav button").forEach(x => x.setAttribute("aria-selected", x.dataset.tab === tab));
  document.querySelectorAll("section.tab").forEach(s => s.classList.toggle("on", s.id === tab));
  try { localStorage.setItem("mahros-tab", tab); } catch(e) {}
  render(tab === "evidence" ? (EV.sub || "trust") : tab);
}
const EV = {sub: "trust"};
function showSub(sub){
  EV.sub = sub;
  document.querySelectorAll("#evnav button").forEach(x => x.setAttribute("aria-selected", x.dataset.sub === sub));
  document.querySelectorAll("#evidence .subtab").forEach(d => d.classList.toggle("on", d.id === sub));
  render(sub);
}
document.querySelectorAll("#mainnav button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
document.querySelectorAll("#evnav button").forEach(b => b.addEventListener("click", () => showSub(b.dataset.sub)));

// ---------------------------------------------------------------- tiny SVG charts
function svgEl(w, h){ return `<svg viewBox="0 0 ${w} ${h}" role="img">`; }
function lineChart(series, opt){
  // series: [{points:[[x,y]], color, width, dash}] ; x = Date, y = number
  const W = opt.w || 760, H = opt.h || 240, L = 46, R = 10, T = 10, B = 26;
  const xs = series.flatMap(s => s.points.map(p => +p[0]));
  const ys = series.flatMap(s => s.points.map(p => p[1]).filter(v => v != null));
  (opt.bands||[]).forEach(b => b.points.forEach(p => { if(p[1]!=null) ys.push(p[1]); if(p[2]!=null) ys.push(p[2]); }));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = opt.ymin ?? Math.min(...ys), y1 = opt.ymax ?? Math.max(...ys);
  if (y1 - y0 < 1e-9) { y1 += 1; y0 -= 1; }
  const pad = (y1-y0)*0.06; if(opt.ymin==null) y0 -= pad; if(opt.ymax==null) y1 += pad;
  const X = v => L + (W-L-R) * (v - x0) / ((x1 - x0) || 1);
  const Y = v => T + (H-T-B) * (1 - (v - y0) / (y1 - y0));
  let s = svgEl(W, H);
  for (let i = 0; i <= 4; i++){ const v = y0 + (y1-y0)*i/4; s += `<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${css('--line')}"/>`;
    s += `<text x="${L-6}" y="${Y(v)+4}" text-anchor="end">${opt.yfmt ? opt.yfmt(v) : v.toFixed(0)}</text>`; }
  const ticks = 5; for (let i = 0; i <= ticks; i++){ const v = x0 + (x1-x0)*i/ticks; const d = new Date(v);
    s += `<text x="${X(v)}" y="${H-6}" text-anchor="middle">${d.toLocaleDateString(undefined,{month:"short",year:"2-digit"})}</text>`; }
  (opt.bands||[]).forEach(b => {
    const pts = b.points.filter(p => p[1]!=null && p[2]!=null);
    if (!pts.length) return;
    const up = pts.map(p => `${X(+p[0])},${Y(p[2])}`).join(" ");
    const dn = pts.slice().reverse().map(p => `${X(+p[0])},${Y(p[1])}`).join(" ");
    s += `<polygon points="${up} ${dn}" fill="${b.color}" stroke="none"/>`;
  });
  if (opt.hline != null) s += `<line x1="${L}" x2="${W-R}" y1="${Y(opt.hline)}" y2="${Y(opt.hline)}" stroke="${css('--red')}" stroke-dasharray="4 4"/>`;
  series.forEach(se => {
    let d = "", pen = false;
    se.points.forEach(p => { if (p[1] == null){ pen = false; return; } d += (pen ? "L" : "M") + X(+p[0]) + "," + Y(p[1]); pen = true; });
    s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="${se.width||2}" ${se.dash ? `stroke-dasharray="${se.dash}"` : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
    (se.marks||[]).forEach(p => { if(p[1]!=null) s += `<circle cx="${X(+p[0])}" cy="${Y(p[1])}" r="4.5" fill="${css('--red')}" stroke="${css('--panel')}" stroke-width="1.5"><title>${esc(p[2]||"")}</title></circle>`; });
  });
  return s + "</svg>";
}
function hbars(rows, opt={}){
  // rows: [{label, value (0..1), note, color}]
  const W = 760, rowH = 34, L = 210, R = 70, H = rows.length * rowH + 6;
  const max = opt.max ?? Math.max(...rows.map(r => r.value), 1e-9);
  let s = svgEl(W, H);
  rows.forEach((r, i) => {
    const y = 4 + i*rowH, w = (W-L-R) * Math.max(0, r.value) / max;
    s += `<text x="${L-10}" y="${y+19}" text-anchor="end" style="fill:${css('--ink')};font-size:13px">${esc(r.label)}</text>`;
    s += `<rect x="${L}" y="${y+6}" width="${w}" height="18" rx="4" fill="${r.color || css('--chart1')}"/>`;
    s += `<text x="${L+w+8}" y="${y+19}" style="fill:${css('--ink')};font-size:13px;font-weight:600">${opt.fmt ? opt.fmt(r.value) : pct(r.value)}</text>`;
  });
  return s + "</svg>";
}

// ---------------------------------------------------------------- OVERVIEW
async function renderOverview(){
  const [r1, r2, r3, man] = await Promise.all([get("rq1_trust_audit.json"), get("rq2_forecast.json"), get("rq3_coordination.json"), get("manifest.json")]);
  const p = r1.prevalence, h1 = r2.horizons["1"], h2 = r2.horizons["2"], m = r3.arms.mahros, o = r3.arms.oracle;
  const cards = [
    {k:"1 · Trust", big: pct(p.share_hospitals_with_any_red,0), t:`of hospitals sent at least one report that cannot be right — most often a patient count frozen for weeks. Reports the Steward flagged were ${r1.hhs_labels.enrichment_red_vs_green.toFixed(1)}× more likely to be corrected later by the government itself.`, tab:"trust"},
    {k:"2 · Forecast", big: h1.mae_points.model_trusted.toFixed(1) + " pts", t:`average error predicting next week's occupancy, against ${h1.mae_points.persistence.toFixed(1)} for "same as this week". The gain is larger two weeks ahead (${h2.mae_points.model_trusted.toFixed(1)} vs ${h2.mae_points.persistence.toFixed(1)}).`, tab:"forecast"},
    {k:"3 · Coordination", big: pct(m.share_of_overload_absorbed,0), t:`of the patient-days spent above a 90% safe occupancy level could have been absorbed by hospitals with room within 80 km, checked against what they reported the next week. Perfect foresight would reach ${pct(o.share_of_overload_absorbed,0)}.`, tab:"coord"},
  ];
  $("#ov-cards").innerHTML = cards.map(c => `<div class="card"><div class="small muted">${c.k}</div><div class="big">${c.big}</div><div class="small">${c.t}</div><p style="margin:10px 0 0"><button class="act" onclick="document.querySelector('nav button[data-tab=${c.tab}]').click()">See the evidence →</button></p></div>`).join("");
  const c = man.corrected, rw = man.raw || {};
  document.querySelectorAll(".ov-nhosp").forEach(el => el.textContent = num(p.hospitals));
  $("#ov-data").innerHTML = `<table>
    <tr><th>Dataset</th><td><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a> — ${esc(c.publisher)}, ${esc(c.licence)}</td></tr>
    <tr><th>Size</th><td>${num(c.rows)} weekly hospital reports (corrected) and ${num(rw.rows)} (raw, before government correction); ${num(p.hospitals)} general and critical-access hospitals analysed</td></tr>
    <tr><th>Period</th><td>August 2020 – April 2024 (federal reporting mandate)</td></tr>
    <tr><th>Fingerprint</th><td class="hash">SHA-256 ${esc(c.sha256)}</td></tr>
    <tr><th>Downloaded</th><td>${esc(c.fetched_at)}</td></tr></table>`;
  $("#foot").innerHTML = `Data: U.S. Department of Health &amp; Human Services, public domain · downloaded ${esc(c.fetched_at.slice(0,10))} · every number on this page is read from <span class="kbd">results/</span>, produced by the scripts in <span class="kbd">experiments/</span>.`;
}

// ---------------------------------------------------------------- TRUST
async function renderTrust(){
  const [r1, tr] = await Promise.all([get("rq1_trust_audit.json"), get("trust.json")]);
  const p = r1.prevalence, ch = r1.chance, hl = r1.hhs_labels;
  $("#tr-answer").textContent = `Mostly — but not always. ${pct(p.level_share.RED,1)} of weekly reports cannot be right, and ${num(p.hospitals_with_any_red)} of ${num(p.hospitals)} hospitals (${pct(p.share_hospitals_with_any_red,0)}) sent at least one. The Data Steward agent catches them and says why.`;
  const lv = [["GREEN","Usable as reported"],["AMBER","Usable, minor issue"],["RED","Cannot be right"],["MISSING","Nothing usable"]];
  $("#tr-levels").innerHTML = lv.map(([k,t]) => `<div class="card"><span class="pill ${k}">${k}</span><div class="big">${pct(p.level_share[k]||0,1)}</div><div class="small muted">${t} · ${num(p.level_count[k]||0)} reports</div></div>`).join("");
  const rules = r1.rules;
  $("#tr-rules").innerHTML = `<tr><th>Check</th><th>Verdict</th><th>In plain words</th><th class="n">Reports</th></tr>` +
    Object.entries(rules).map(([code, r]) => `<tr><td><b>${esc(r.title)}</b></td><td><span class="pill ${r.level}">${r.level}</span></td><td class="small">${esc(r.explain)}</td><td class="n">${num(p.rule_counts[code]||0)}</td></tr>`).join("");
  const sel = $("#tr-pick");
  sel.innerHTML = tr.examples.map((e,i) => `<option value="${i}">${esc(e.title)}</option>`).join("");
  const draw = () => {
    const e = tr.examples[+sel.value];
    $("#tr-ex-text").innerHTML = `<p style="margin:0 0 8px"><b>${esc(e.hospital)}</b>, ${esc(e.city)}, ${esc(e.state)} — flagged ${esc(e.flag_week)}. ${esc(e.explain)}</p>`;
    const pts = k => e.series.map(s => [new Date(s.week), s[k]]);
    const marks = e.series.filter(s => s.level === "RED").map(s => [new Date(s.week), s.used, s.why.join(", ")]);
    $("#tr-ex-chart").innerHTML = lineChart([
      {points: pts("beds"), color: css("--chart3"), width: 1.5, dash: "5 4"},
      {points: pts("used"), color: css("--chart1"), width: 2.2, marks}], {h: 230});
  };
  sel.onchange = draw; draw();
  $("#tr-chance").innerHTML = `<p style="margin:0">An honestly varying patient count repeats exactly from one week to the next ${pct(ch.p_repeat,2)} of the time. Three identical weeks in a row should therefore happen about <b>${num(ch.frozen_flags_expected_by_chance)}</b> times by chance across ${num(ch.eligible_weeks)} eligible weeks.</p>
    <p style="margin:8px 0 0">It happened <b>${num(ch.frozen_flags_observed)}</b> times. Chance explains about ${pct(ch.share_explainable_by_chance,0)} of them.</p>`;
  const bands = hl.recall_by_census_correction_size;
  $("#tr-hhs").innerHTML = `<p style="margin:0">The government published both the original reports and a corrected version. Of the reports the Steward marked RED, <b>${pct(hl.share_of_raw_red_that_hhs_changed,0)}</b> were later changed by the government, against <b>${pct(hl.share_of_raw_green_that_hhs_changed,1)}</b> of GREEN ones — <b>${hl.enrichment_red_vs_green.toFixed(1)}×</b> more often.</p>
    <table style="margin-top:8px"><tr><th>Size of the government's correction</th><th class="n">Corrections</th><th class="n">Also flagged RED</th></tr>
    ${Object.entries(bands).map(([k,v]) => `<tr><td>${esc(k)}</td><td class="n">${num(v.n)}</td><td class="n">${pct(v.recall_red,0)}</td></tr>`).join("")}</table>
    <p class="muted" style="margin:6px 0 0">Most government corrections are adjustments of about 1%, which no check should flag. Big corrections are caught far more often.</p>`;
  $("#tr-planted").innerHTML = `<tr><th>Planted mistake</th><th class="n">Times planted</th><th class="n">Caught</th></tr>` +
    Object.values(r1.planted).map(v => `<tr><td>${esc(v.description)}</td><td class="n">${num(v.n)}</td><td class="n"><b>${pct(v.caught,0)}</b></td></tr>`).join("") +
    `<tr><td colspan="3" class="small muted">Correct neighbouring weeks wrongly flagged: ${num(Object.values(r1.planted).reduce((a,v)=>a+v.collateral_alarms_per_episode*v.n,0))} across all ${num(Object.values(r1.planted).reduce((a,v)=>a+v.n,0))} planted mistakes.</td></tr>`;
  const months = Object.keys(tr.monthly_share).sort();
  const ser = k => months.map(m => [new Date(m+"-01"), tr.monthly_share[m][k]]);
  $("#tr-month").innerHTML = lineChart([
    {points: ser("RED"), color: css("--red")}, {points: ser("MISSING"), color: css("--grey")},
    {points: ser("AMBER"), color: css("--amber")}], {h: 220, ymin: 0, yfmt: v => (100*v).toFixed(0)+"%"});
}

// ---------------------------------------------------------------- FORECAST
async function renderForecast(){
  const [r2, fc] = await Promise.all([get("rq2_forecast.json"), get("forecast.json")]);
  const H = r2.horizons, h1 = H["1"];
  const d1 = h1.vs_persistence.model_trusted;
  $("#fc-answer").textContent = `Partly. Our forecaster is reliably better than "next week = this week", but by a small margin one week ahead (${h1.mae_points.model_trusted.toFixed(2)} vs ${h1.mae_points.persistence.toFixed(2)} points). Its 90% ranges contain the true value ${pct(h1.interval.coverage,0)} of the time, as promised.`;
  const rows = [["persistence","Next week = this week"],["mean4","Average of the last 4 weeks"],["model_raw","Our model, trained on every report as published"],["model_trusted","Our model, untrusted reports removed (used by MAHROS)"]];
  const best = h => Math.min(...rows.map(r => H[h].mae_points[r[0]]));
  $("#fc-table").innerHTML = `<tr><th>Method</th><th class="n">1 week ahead</th><th class="n">2 weeks</th><th class="n">4 weeks</th></tr>` +
    rows.map(([k,t]) => `<tr><td>${t}</td>${["1","2","4"].map(h => { const v = H[h].mae_points[k]; return `<td class="n">${v === best(h) ? "<b>"+v.toFixed(2)+"</b>" : v.toFixed(2)}</td>`; }).join("")}</tr>`).join("") +
    `<tr><td class="small muted">Range promised to hold the truth 90% of the time</td>${["1","2","4"].map(h => `<td class="n small muted">held ${pct(H[h].interval.coverage,1)}</td>`).join("")}</tr>` +
    `<tr><td class="small muted">Hospital-weeks scored</td>${["1","2","4"].map(h => `<td class="n small muted">${num(H[h].n_rows)}</td>`).join("")}</tr>`;
  const raw = h1.trusted_vs_raw_model;
  $("#fc-not").innerHTML = `
    <li>One week ahead the improvement is small: ${Math.abs(d1.diff_points).toFixed(2)} points (95% range ${Math.abs(d1.ci95_points[1]).toFixed(2)}–${Math.abs(d1.ci95_points[0]).toFixed(2)}). Four weeks ahead, a plain 4-week average does better than our model.</li>
    <li>Removing untrusted reports did <b>not</b> make forecasts more accurate on average (it was ${raw.diff_points.toFixed(2)} points worse). Bad reports are rare; their harm shows up in decisions when they are large — see Question 3.</li>
    <li>Forecasts are for whole-hospital weekly occupancy, not for a ward, a specialty or a day.</li>`;
  const sel = $("#fc-pick");
  sel.innerHTML = fc.examples.map((e,i) => `<option value="${i}">${esc(e.hospital)} (${esc(e.state)}, ${num(e.beds)} beds)</option>`).join("");
  const draw = () => {
    const e = fc.examples[+sel.value];
    const P = k => e.series.map(s => [new Date(s.week), s[k]]);
    $("#fc-chart").innerHTML = lineChart([
      {points: P("actual"), color: css("--chart1"), width: 2.2},
      {points: P("pred"), color: css("--chart2"), width: 1.8}],
      {h: 250, bands: [{color: css("--band"), points: e.series.map(s => [new Date(s.week), s.lo, s.hi])}],
       yfmt: v => (100*v).toFixed(0)+"%", hline: 0.9});
  };
  sel.onchange = draw; draw();
}

// ---------------------------------------------------------------- COORDINATION
async function renderCoord(){
  const [r3, idx] = await Promise.all([get("rq3_coordination.json"), get("index.json")]);
  const A = r3.arms, prm = r3.params;
  $("#co-answer").textContent = `Yes, a lot of it. In 2023–2024, about ${pct(A.mahros.share_of_overload_absorbed,0)} of the patient-days hospitals spent above ${pct(prm.theta,0)} full could have been absorbed by hospitals within ${prm.radius_km} km that really had room the following week. Perfect foresight would reach ${pct(A.oracle.share_of_overload_absorbed,0)}.`;
  const arms = [["none","No coordination"],["greedy","Simple rule: nearest hospital with room"],["persistence","Optimised, using “next week = this week”"],["no_trust","Optimised, believing every report"],["mahros","MAHROS (forecast + Data Steward + optimiser)"],["oracle","Ceiling: perfect knowledge of next week"]];
  $("#co-arms").innerHTML = hbars(arms.map(([k,t]) => ({label: t, value: A[k].share_of_overload_absorbed, color: k === "mahros" ? css("--chart1") : k === "oracle" ? css("--chart3") : css("--chart2")})), {max: Math.max(A.oracle.share_of_overload_absorbed, 0.01)});
  const c = r3.comparisons;
  $("#co-arms-note").innerHTML = `Honest reading: almost all of the gain comes from coordinating at all. On real data, the optimiser, the forecaster and the trust checks each change the result by about a percentage point (MAHROS minus simple rule: ${num(c.mahros_vs_greedy.mean_weekly_diff_patient_days)} patient-days a week; minus "next week = this week": ${num(c.mahros_vs_persistence.mean_weekly_diff_patient_days)}). Scored over ${A.mahros.weeks} weeks; ${num(A.mahros.overload_patient_days)} patient-days were above the safe level in total.`;
  // planted
  const pe = r3.planted_errors || {};
  $("#co-planted").innerHTML = `<tr><th>Reports with a planted mistake</th><th class="n">MAHROS absorbs</th><th class="n">Believing every report absorbs</th><th class="n">Wrongly planned onto full hospitals*</th></tr>` +
    Object.entries(pe).map(([rate, v]) => `<tr><td>${pct(+rate,0)} (${num(v.reports_corrupted)} reports)</td><td class="n">${pct(v.arms.mahros.share_of_overload_absorbed,1)}</td><td class="n">${pct(v.arms.no_trust.share_of_overload_absorbed,1)}</td><td class="n">${num(v.arms.mahros.overfill_if_unchecked_patient_days)} vs ${num(v.arms.no_trust.overfill_if_unchecked_patient_days)}</td></tr>`).join("");
  $("#co-planted-note").textContent = "* Patient-days the plan would have pushed into hospitals above the safe level had nobody checked (MAHROS vs believing every report). Hospital agents decline these, which is why they never become real transfers.";
  $("#co-sens").innerHTML = `<tr><th>Change one assumption</th><th class="n">MAHROS absorbs</th><th class="n">Ceiling</th></tr>` +
    `<tr><td><b>As used: ${pct(prm.theta,0)} safe level, ${prm.radius_km} km, ${pct(prm.kappa,0)} per week</b></td><td class="n"><b>${pct(A.mahros.share_of_overload_absorbed,1)}</b></td><td class="n">${pct(A.oracle.share_of_overload_absorbed,1)}</td></tr>` +
    Object.entries(r3.sensitivity).map(([k,v]) => `<tr><td>${esc(k.replace("theta","safe level").replace("kappa","weekly cap").replace("radius","radius"))}</td><td class="n">${pct(v.mahros_share,1)}</td><td class="n">${pct(v.oracle_share,1)}</td></tr>`).join("");
  // by state
  const bs = r3.by_state || {}, M = bs.mahros || {}, O = bs.oracle || {};
  const st = Object.entries(M).filter(([,v]) => v.overload_patient_days > 0).sort((a,b) => b[1].overload_patient_days - a[1].overload_patient_days).slice(0, 12);
  $("#co-states").innerHTML = `<tr><th>State</th><th class="n">Patient-days above safe level</th><th class="n">MAHROS absorbs</th><th class="n">Ceiling</th></tr>` +
    st.map(([k,v]) => `<tr><td>${esc(k)}</td><td class="n">${num(v.overload_patient_days)}</td><td class="n">${pct(v.share_absorbed,0)}</td><td class="n">${pct((O[k]||{}).share_absorbed,0)}</td></tr>`).join("");
  try {
    const hc = await get("houston_case_study.json"), g = hc.geometry, pl = hc.plans;
    $("#co-houston").innerHTML = `<p style="margin:0">For ${hc.hospitals_matched} Houston hospitals we have real driving times. Straight-line distance and driving time agree closely (correlation ${g.corr_straight_vs_drive.toFixed(2)}; roads are a median ${g.road_over_straight_median.toFixed(2)}× longer).</p>
      <p style="margin:8px 0 0">Re-planning all ${hc.weeks} weeks with a <b>60-minute drive</b> instead of <b>80 km straight line</b>: absorbed ${pct(pl.drive_60min.share_absorbed,1)} vs ${pct(pl.straight_80km.share_absorbed,1)}, and ${pct(hc.weighted_overlap_of_transfers,0)} of the transfers are the same.</p>
      <p class="muted" style="margin:8px 0 0">Houston itself absorbs far less than the national average: its hospitals are often all full at the same time.</p>`;
  } catch (e) { $("#co-houston").textContent = "Houston case study not built."; }
  // explorer
  const wsel = $("#co-week"), ssel = $("#co-state");
  if (!wsel.options.length){
    wsel.innerHTML = idx.weeks.map(w => `<option value="${w.week}">${esc(w.label)} — ${w.week}</option>`).join("");
    const pref = ["TX","CA","NY","FL","AZ"].find(s => idx.states.includes(s)) || idx.states[0];
    ssel.innerHTML = idx.states.map(s => `<option ${s===pref?"selected":""}>${s}</option>`).join("");
    wsel.onchange = ssel.onchange = drawWeek;
  }
  drawWeek();
}
async function drawWeek(){
  const wk = $("#co-week").value, st = $("#co-state").value;
  const run = (await get(`run_${wk}.json`))[st];
  if (!run){ $("#co-map").innerHTML = "<p class='muted'>No hospitals in this state.</p>"; return; }
  const T = run.totals;
  $("#co-totals").innerHTML = [
    ["Hospitals", num(T.hospitals), `${num(T.red_reports)} RED, ${num(T.missing_reports)} missing`],
    ["Patient-days above safe level", num(T.overload_patient_days), "next week, trusted reports"],
    ["Proposed to move", num(T.planned_patient_days), "patient-days"],
    ["Actually possible", num(T.moved_patient_days), T.share_absorbed == null ? "nothing to absorb" : pct(T.share_absorbed,0) + " of the excess"],
  ].map(([k,v,s]) => `<div class="card"><div class="small muted">${k}</div><div class="big" style="font-size:24px">${v}</div><div class="small muted">${s}</div></div>`).join("");
  // map
  const hs = run.hospitals.filter(h => h.lat != null && h.lon != null);
  const W = 520, Hh = 420, pad = 18;
  const lats = hs.map(h => h.lat), lons = hs.map(h => h.lon);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2, kx = Math.cos(midLat*Math.PI/180);
  const x0 = Math.min(...lons)*kx, x1 = Math.max(...lons)*kx, y0 = Math.min(...lats), y1 = Math.max(...lats);
  const sc = Math.min((W-2*pad)/((x1-x0)||1), (Hh-2*pad)/((y1-y0)||1));
  const P = h => [pad + (h.lon*kx - x0)*sc, Hh - pad - (h.lat - y0)*sc];
  const byId = Object.fromEntries(hs.map(h => [h.id, h]));
  let s = svgEl(W, Hh) + `<rect x="0" y="0" width="${W}" height="${Hh}" rx="8" fill="${css('--bg')}"/>`;
  run.proposals.forEach(p => { const a = byId[p.from], b = byId[p.to]; if(!a||!b) return; const [ax,ay] = P(a), [bx,by] = P(b);
    const done = p.executed > 0.01;
    s += `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="${done ? css('--accent') : css('--grey')}" stroke-width="${done ? 1.2 + Math.min(4, p.executed/3) : 1}" ${done ? "" : 'stroke-dasharray="3 3"'} opacity=".8"><title>${esc(p.from_name)} → ${esc(p.to_name)}: ${p.executed.toFixed(1)} of ${p.patients_per_day.toFixed(1)} patients/day</title></line>`; });
  hs.forEach(h => { const [x,y] = P(h); const trusted = h.level === "GREEN" || h.level === "AMBER";
    const col = !trusted ? css('--grey') : (h.forecast != null && h.forecast > 0.9) ? css('--red') : css('--green');
    const r = 3 + Math.sqrt(h.beds || 20) / 4;
    s += `<circle cx="${x}" cy="${y}" r="${r}" fill="${col}" fill-opacity="${trusted ? .85 : .35}" stroke="${css('--panel')}" stroke-width="1"><title>${esc(h.name)} (${esc(h.city)}) — ${h.level}; now ${pct(h.occupancy_now,0)}, forecast ${pct(h.forecast,0)}${h.reasons.length ? "; " + esc(h.reasons.map(r=>r.title).join(", ")) : ""}</title></circle>`; });
  $("#co-map").innerHTML = s + "</svg>";
  const resp = {}; run.responses.forEach(r => { (resp[r.hospital] = resp[r.hospital] || []).push(r); });
  const props = run.proposals.slice().sort((a,b) => b.patients_per_day - a.patients_per_day);
  $("#co-props").innerHTML = props.length ? props.slice(0, 60).map(p => {
    const sr = (resp[p.from]||[]).find(r => r.role === "send"), rr = (resp[p.to]||[]).find(r => r.role === "receive");
    const verdict = p.executed > 0.01 ? `<span class="pill GREEN">${p.executed.toFixed(1)} moved</span>` : `<span class="pill MISSING">not possible</span>`;
    return `<div class="prop"><b>${esc(p.from_name)}</b> → <b>${esc(p.to_name)}</b> · ${p.patients_per_day.toFixed(1)} patients/day proposed · ${verdict}
      <div class="small muted">${esc(p.why)}</div>
      ${sr ? `<div class="small">Sender: ${esc(sr.why)}.</div>` : ""}${rr ? `<div class="small">Receiver: ${esc(rr.why)}.</div>` : ""}</div>`; }).join("") +
    (props.length > 60 ? `<p class="small muted">…and ${props.length-60} more.</p>` : "")
    : "<p class='muted'>No hospital was forecast to be above the safe level with room nearby — nothing to propose.</p>";
}

// ---------------------------------------------------------------- RESEARCH LEDGER (published with results)
async function renderResearchLedger(){
  const d = await (await fetch("/api/ledger")).json();
  const v = d.verify;
  $("#au-status").innerHTML = v.ok
    ? `<p class="ok" style="margin:0">✓ ${num(v.blocks)} weekly pages, ${num(v.entries)} lines, rebuilt from the raw entries.</p>
       <p style="margin:6px 0 0">${d.rebuilt_matches_published ? "It lands on exactly the fingerprint published with the results:" : "Rebuilt fingerprint:"}</p><p class="hash" style="margin:4px 0 0">${esc(v.head)}</p>`
    : `<p class="bad" style="margin:0">✗ The published research log does not verify (page ${v.first_bad_block}).</p>`;
}

// ---------------------------------------------------------------- LIVE
const LV = {playing: false, busy: false, data: null, stage: -1, pos: {}, setup: false, names: {}};
const STEPS = [
  ["report", "1 · Report", "Hospitals send numbers", "--c-hosp", "Hospital agents"],
  ["check", "2 · Check", "Bad reports caught", "--c-stew", "Data Steward agent"],
  ["forecast", "3 · Forecast", "Next week predicted", "--c-fore", "Forecast agent"],
  ["plan", "4 · Plan", "Moves suggested", "--c-coord", "State coordinator agent"],
  ["answer", "5 · Answer", "Hospitals say yes / no", "--c-hosp", "Hospital agents"],
  ["result", "6 · Result", "What it achieved", "--ink", "Result"]];
const TONE = {red: "--red", inject: "--red", saved: "--red", miss: "--amber", green: "--green",
              amber: "--amber", grey: "--grey", ledger: "--c-led"};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fmtDate = d => new Date(d + "T00:00:00").toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric"});
async function lvApi(path, method = "GET"){
  const r = await fetch("/api/live/" + path, {method});
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
  return d;
}
function occColor(occ){
  if (occ == null) return css("--grey");
  return occ >= 0.9 ? css("--red") : occ >= 0.8 ? css("--amber") : css("--green");
}
function lvSteps(){
  $("#lv-steps").innerHTML = STEPS.map(([k, n, t], i) =>
    `<li class="${i < LV.stage ? "done" : i === LV.stage ? "active" : ""}"><b>${n}</b>${t}</li>`).join("");
}
// opt.mode: "now" | "forecast" | "next"; opt.arcs: [{from, to, moved?}]
function lvDrawMap(hs, opt){
  const pts = hs.filter(h => h.lat != null && h.lon != null);
  if (!pts.length){ $("#lv-map").innerHTML = "<div class='empty'>No hospitals.</div>"; return; }
  const W = 640, H = 480, pad = 26;
  // Zoom: fit the hospitals this step is about (plus neighbours), else the whole state.
  const zs = (opt.zoom || []).map(id => pts.find(h => h.id === id)).filter(Boolean);
  const box = zs.length ? zs : pts;
  const lats = box.map(h => h.lat), lons = box.map(h => h.lon);
  const kx = Math.cos(((Math.min(...lats) + Math.max(...lats)) / 2) * Math.PI / 180);
  let x0 = Math.min(...lons) * kx, x1 = Math.max(...lons) * kx, y0 = Math.min(...lats), y1 = Math.max(...lats);
  if (zs.length){
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const half = Math.max(x1 - x0, (y1 - y0) * (W / H), 0.45) * 0.62;
    x0 = cx - half; x1 = cx + half; y0 = cy - half * H / W; y1 = cy + half * H / W;
  }
  const sc = Math.min((W - 2 * pad) / ((x1 - x0) || 1), (H - 2 * pad) / ((y1 - y0) || 1));
  const ox = (W - (x1 - x0) * sc) / 2, oy = (H - (y1 - y0) * sc) / 2;
  LV.pos = {};
  pts.forEach(h => { LV.pos[h.id] = [ox + (h.lon * kx - x0) * sc, H - oy - (h.lat - y0) * sc]; });
  const focus = new Set(opt.focus || []);
  const occOf = h => opt.mode === "forecast" ? h.forecast : opt.mode === "next"
      ? (h.trusted_next && h.beds_next ? h.used_next / h.beds_next : null) : (h.occupancy_now ?? h.occupancy);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img"><defs><marker id="lv-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="${css('--accent')}"/></marker></defs>
    <rect width="${W}" height="${H}" rx="10" fill="${css('--bg')}"/>`;
  (opt.arcs || []).forEach(a => {
    const p = LV.pos[a.from], q = LV.pos[a.to]; if (!p || !q) return;
    s += a.moved != null
      ? `<line x1="${p[0]}" y1="${p[1]}" x2="${q[0]}" y2="${q[1]}" stroke="${css('--accent')}" stroke-width="${(1.5 + Math.min(5, a.moved / 4)).toFixed(1)}" marker-end="url(#lv-arrow)" opacity=".9"/>`
      : `<line x1="${p[0]}" y1="${p[1]}" x2="${q[0]}" y2="${q[1]}" stroke="${css('--c-coord')}" stroke-width="1.6" stroke-dasharray="5 4" opacity=".85"/>`;
  });
  pts.forEach(h => {
    const [x, y] = LV.pos[h.id], bad = opt.flags && (h.level === "RED" || h.level === "MISSING");
    const r = 3.5 + Math.sqrt(h.beds || 25) / 3, f = focus.has(h.id), occ = occOf(h);
    if (bad){
      s += `<g opacity="${f ? 1 : .75}"><circle cx="${x}" cy="${y}" r="${r}" fill="${css('--panel')}" stroke="${css('--grey')}" stroke-width="2" stroke-dasharray="3 2"/>
        <path d="M${x - r * .6},${y - r * .6}L${x + r * .6},${y + r * .6}M${x + r * .6},${y - r * .6}L${x - r * .6},${y + r * .6}" stroke="${css('--red')}" stroke-width="2"/>
        <title>${esc(h.name)} — report set aside</title></g>`;
    } else {
      s += `<circle cx="${x}" cy="${y}" r="${r}" fill="${occColor(occ)}" fill-opacity="${occ == null ? .35 : .88}" stroke="${f ? css('--ink') : css('--panel')}" stroke-width="${f ? 3 : 1}"><title>${esc(h.name)} — ${occ == null ? "no trusted number" : pct(occ, 0) + " full"}</title></circle>`;
    }
  });
  // Numbered badges match the numbers in the text panel (names would overlap).
  Object.entries(opt.badges || {}).forEach(([id, n]) => {
    const p = LV.pos[id]; if (!p) return;
    const bx = p[0] + 10, by = p[1] - 10, on = focus.has(id);
    s += `<g opacity="${on ? 1 : .55}"><circle cx="${bx}" cy="${by}" r="10" fill="${css('--ink')}" stroke="${css('--panel')}" stroke-width="1.5"/><text x="${bx}" y="${by + 4}" text-anchor="middle" style="fill:${css('--panel')};font-size:12px;font-weight:700">${n}</text></g>`;
  });
  $("#lv-map").innerHTML = s + "</svg>";
  const mode = {now: "how full this week", forecast: "expected next week", next: "real numbers next week"}[opt.mode];
  $("#lv-map-mode").textContent = "Colour = " + mode;
  $("#lv-legend").innerHTML = `<span><i class="dot" style="background:var(--green)"></i>Has room (under 80%)</span><span><i class="dot" style="background:var(--amber)"></i>Busy (80–90%)</span><span><i class="dot" style="background:var(--red)"></i>Too full (over 90%)</span>` +
    (opt.flags ? `<span><b style="color:var(--red)">✕</b> Report set aside</span>` : "") +
    ((opt.arcs || []).some(a => a.moved == null) ? `<span><i style="background:var(--c-coord)"></i>Suggested move</span>` : "") +
    ((opt.arcs || []).some(a => a.moved != null) ? `<span><i style="background:var(--accent)"></i>Patients could move</span>` : "");
}
function lvShowStage(){
  lvSteps();
  const d = LV.data, run = d.run, st = d.stages[LV.stage];
  const col = STEPS[LV.stage][3], who = STEPS[LV.stage][4];
  const nums = st.numbers.map(n => `<div><div class="v" style="color:${css(n.tone ? (TONE[n.tone] || "--ink") : "--ink")}">${esc(n.value)}</div><div class="l">${esc(n.label)}</div></div>`).join("");
  const badges = {}; let nb = 0;
  [...st.items.flatMap(it => it.focus || []), ...(st.map.focus || [])].forEach(id => { if (!(id in badges) && nb < 9) badges[id] = ++nb; });
  const bdg = ids => (ids || []).filter(id => id in badges).map(id => `<span class="bdg">${badges[id]}</span>`).join("");
  const items = st.items.map(it => `<div class="item" data-focus="${esc((it.focus || []).join(","))}" style="border-left-color:${css(TONE[it.tone] || "--line")}">${bdg(it.focus)}${esc(it.text)}</div>`).join("");
  const story = st.story ? `<div class="story" data-focus="${esc(st.story.from.id + "," + st.story.to.id)}"><b class="k">Example from this week · ${bdg([st.story.from.id])}→ ${bdg([st.story.to.id])}</b>${esc(st.story.text)}</div>` : "";
  $("#lv-stage").innerHTML = `<div class="who" style="color:${css(col)}">Step ${LV.stage + 1} of 6 · ${esc(who)}</div>
    <h2>${esc(st.title)}</h2><p class="cap">${esc(st.caption)}</p><div class="nums">${nums}</div>${story}${items}
    <p class="small muted" style="margin:12px 0 0">${LV.stage < 5 ? "Press <b>Next step ›</b> to continue." : "Press <b>Next step ›</b> to start the next week."}</p>`;
  const arcs = st.map.arcs === "planned" ? run.proposals.map(p => ({from: p.from, to: p.to}))
             : st.map.arcs === "moved" ? run.proposals.filter(p => p.executed > 0.5).map(p => ({from: p.from, to: p.to, moved: p.executed})) : [];
  const zoom = LV.stage >= 3 && Object.keys(badges).length ? Object.keys(badges) : [];
  const draw = focus => lvDrawMap(run.hospitals, {mode: st.map.color, flags: st.map.flags, arcs, focus, badges, zoom});
  draw(st.map.focus.length ? st.map.focus : Object.keys(badges));
  // Hovering a line in the panel highlights those hospitals on the map.
  document.querySelectorAll("#lv-stage .item").forEach(el => {
    el.onmouseenter = () => { const f = el.dataset.focus ? el.dataset.focus.split(",") : []; if (f.length) draw(f); };
    el.onmouseleave = () => draw(st.map.focus.length ? st.map.focus : Object.keys(badges));
  });
  $("#lv-map-title").textContent = `${d.state_name} · week of ${fmtDate(run.week)}` + (zoom.length ? " · zoomed in" : "");
  if (LV.stage === 5){ lvHistory(d.history); lvLedger(d.ledger); }
}
function lvIntro(st, hs){
  LV.stage = -1; lvSteps();
  $("#lv-stage").innerHTML = `<div class="who" style="color:${css('--accent')}">Before we start</div>
    <h2>You are the ${esc(st.state_name)} health department</h2>
    <p class="cap">Every dot on the map is a real hospital in ${esc(st.state_name)}. Some will be too full next week while others nearby have empty beds. Software agents work together to find those patients a bed — and to make sure nobody acts on a wrong number.</p>
    <div class="item" style="border-left-color:${css('--c-hosp')}"><b>Hospital agents</b> — one per hospital. Send their numbers; decide whether to accept patients.</div>
    <div class="item" style="border-left-color:${css('--c-stew')}"><b>Data Steward</b> — catches reports that cannot be true.</div>
    <div class="item" style="border-left-color:${css('--c-fore')}"><b>Forecaster</b> — predicts how full each hospital will be next week.</div>
    <div class="item" style="border-left-color:${css('--c-coord')}"><b>State coordinator</b> — suggests moving patients to nearby hospitals with room.</div>
    <div class="item" style="border-left-color:${css('--c-led')}"><b>Audit log</b> — writes everything down so nobody can change it later.</div>
    <p class="small muted" style="margin:12px 0 0">Real reports from the week of ${fmtDate(st.week)}. Press <b>Next step ›</b> to begin.</p>`;
  lvDrawMap(hs, {mode: "now", flags: false, arcs: [], focus: []});
  $("#lv-map-title").textContent = `${st.state_name} · ${hs.length} hospitals`;
}
function lvFeed(feed){
  $("#lv-feed").innerHTML = feed.filter(e => !e.silent).map(ev => {
    const tone = ev.level === "RED" || ev.level === "SAVED" ? "--red" : ev.level === "MISS" ? "--amber" : "--line";
    return `<div class="ev" style="border-left-color:${css(tone)}"><span class="tag muted">${esc(ev.agent)}</span>${esc(ev.text)}</div>`;
  }).join("");
}
function lvHistory(h){
  if (!h || !h.length){ $("#lv-hist").textContent = "Each finished week appears here."; return; }
  const W = 360, H = 140, B = 18, n = h.length, bw = Math.max(3, Math.min(22, (W - 10) / n / 2.2));
  const max = Math.max(...h.map(x => x.above_safe), 1);
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  h.forEach((x, i) => {
    const cx = 6 + i * (W - 12) / Math.max(n, 1), y1 = (H - B) * x.above_safe / max, y2 = (H - B) * x.moved / max;
    s += `<rect x="${cx}" y="${H - B - y1}" width="${bw}" height="${y1}" fill="${css('--red')}" opacity=".75"><title>${x.week}: ${num(x.above_safe)} in too-full hospitals</title></rect>`;
    s += `<rect x="${cx + bw}" y="${H - B - y2}" width="${bw}" height="${y2}" fill="${css('--accent')}"><title>${x.week}: ${num(x.moved)} could move</title></rect>`;
  });
  const tot = h.reduce((a, x) => [a[0] + x.above_safe, a[1] + x.moved], [0, 0]);
  s += `<text x="4" y="${H - 3}">${esc(h[0].week)}</text>${n > 1 ? `<text x="${W - 4}" y="${H - 3}" text-anchor="end">${esc(h[n - 1].week)}</text>` : ""}</svg>`;
  $("#lv-hist").innerHTML = s + `<div style="margin-top:4px;color:var(--ink)">${n} week${n > 1 ? "s" : ""}: ${num(tot[1])} of ${num(tot[0])} patients in too-full hospitals could have moved (${tot[0] ? pct(tot[1] / tot[0], 0) : "—"}).</div>`;
}
function lvLedger(l, tampered){
  const chip = $("#lv-chip");
  if (!l || !l.blocks){ chip.className = "chip ok"; chip.textContent = "🔒 Audit log: empty"; $("#lv-ledger").textContent = "Nothing recorded yet."; return; }
  if (l.ok){
    chip.className = "chip ok"; chip.textContent = `🔒 Audit log OK · ${l.blocks} week${l.blocks > 1 ? "s" : ""}`;
    $("#lv-ledger").innerHTML = `<p class="ok" style="margin:0">✓ ${l.blocks} week${l.blocks > 1 ? "s" : ""} written down. Every page still matches its fingerprint.</p><p class="hash muted" style="margin:6px 0 0">${esc(l.head)}</p>`;
  } else {
    chip.className = "chip bad"; chip.textContent = `⚠ Audit log: change detected in week ${l.first_bad_block + 1}`;
    $("#lv-ledger").innerHTML = `<p class="bad" style="margin:0">✗ Someone changed the record — caught.</p>` +
      (tampered ? `<p style="margin:6px 0 0">${esc(tampered.hospital)}'s patient count for the week of ${esc(String(tampered.week).replace(/^[A-Z]{2} /, ""))} was quietly changed from ${tampered.before} to ${tampered.after}. Only that one number was touched, and the check points to exactly that week.</p>` : "") +
      `<p class="muted" style="margin:6px 0 0">Press ↺ Restart for a clean log.</p>`;
  }
}
function lvPending(p){
  $("#lv-pending").innerHTML = (p && p.length) ? p.map(x => `<div class="item" style="border-left-color:${css('--red')}">Next week, <b>${esc(LV.names[x.id] || x.id)}</b> will send a wrong number: ${esc(x.mistake.toLowerCase())}.</div>`).join("") : "";
}
async function lvNext(){
  if (LV.busy) return false;
  LV.busy = true;
  try {
    if (!LV.data || LV.stage >= 5){
      const d = await lvApi("step", "POST");
      if (!d.run){ lvStop(); $("#lv-stage").insertAdjacentHTML("beforeend", "<p class='bad'>That was the last week of data. Press ↺ Restart.</p>"); return false; }
      LV.data = d; LV.stage = 0; lvFeed(d.feed); lvPending(d.pending);
      LV.names = Object.fromEntries(d.run.hospitals.map(h => [h.id, h.name]));
      $("#lv-start").value = String(Math.max(0, d.week_idx - 1));
    } else {
      LV.stage += 1;
    }
    lvShowStage();
    return true;
  } catch (e) {
    lvStop(); $("#lv-stage").insertAdjacentHTML("beforeend", `<p class="bad">Error: ${esc(e.message)}</p>`); return false;
  } finally { LV.busy = false; }
}
function lvStop(){ LV.playing = false; $("#lv-play").textContent = "▶ Auto-play"; }
async function lvPlay(){
  if (LV.playing){ lvStop(); return; }
  LV.playing = true; $("#lv-play").textContent = "⏸ Pause";
  while (LV.playing){
    if (!(await lvNext())) break;
    await sleep(+$("#lv-speed").value);
  }
}
async function lvLoadState(st){
  const hs = await lvApi("hospitals");
  LV.data = null; LV.names = Object.fromEntries(hs.map(h => [h.id, h.name]));
  lvIntro(st, hs); lvHistory(st.history); lvLedger(st.ledger); lvPending(st.pending);
  $("#lv-feed").innerHTML = `<div class="empty">Nothing yet.</div>`;
  const opts = hs.slice().sort((a, b) => a.name.localeCompare(b.name));
  const km = (a, b) => { const r = Math.PI / 180, dl = (b.lat - a.lat) * r, dn = (b.lon - a.lon) * r;
    const x = Math.sin(dl / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dn / 2) ** 2; return 12742 * Math.asin(Math.sqrt(x)); };
  const crowded = h => hs.filter(o => o.id !== h.id && km(h, o) <= 30).length >= 3;
  const fullest = hs.filter(h => h.level === "GREEN" && (h.beds || 0) >= 80 && h.occupancy != null && crowded(h))
                    .sort((a, b) => b.occupancy - a.occupancy)[0];
  $("#lv-hosp").innerHTML = opts.map(h => `<option value="${esc(h.id)}" ${fullest && h.id === fullest.id ? "selected" : ""}>${esc(h.name)}${h.occupancy != null ? " — " + pct(h.occupancy, 0) + " full" : ""}</option>`).join("");
  $("#lv-mistake").value = "lost_digit";
  $("#lv-start").value = String(st.week_idx);
  // Pre-select the hospital where a typo would really misdirect patients this week.
  try {
    const pick = await lvApi("demo_pick");
    if (pick.id){
      $("#lv-hosp").value = pick.id;
      $("#lv-pending").innerHTML = `<div class="small muted" style="margin-top:6px">Pre-selected: if <b>${esc(pick.name)}</b> made this typo this week and nobody checked, about <b>${num(pick.would_receive)}</b> patients would be sent to it although it is full.</div>`;
    }
  } catch (e) {}
}
async function lvRestart(){
  lvStop();
  while (LV.busy) await sleep(100);
  const st = await lvApi(`reset?state=${encodeURIComponent($("#lv-state").value)}&week_idx=${$("#lv-start").value}`, "POST");
  await lvLoadState(st);
}
async function renderLive(){
  const st = await lvApi("status");
  if (!st.ready){
    $("#lv-main").style.display = "none"; $("#lv-wait").style.display = "block";
    $("#lv-wait").innerHTML = st.error
      ? `<div class="q">Live operations</div><div class="a">Live mode is not available here.</div><p class="small muted">${esc(st.error)}<br>It runs on a computer with the downloaded data: <span class="kbd">python experiments/fetch_national.py</span> then <span class="kbd">python experiments/rq2_forecast.py</span>. The other tabs work everywhere.</p>`
      : `<div class="q">Live operations</div><div class="a">Loading about one million real hospital reports…</div><p class="small muted">This takes about 15 seconds when the server starts.</p>`;
    if (!st.error) setTimeout(renderLive, 1500);
    return;
  }
  $("#lv-wait").style.display = "none"; $("#lv-main").style.display = "block";
  if (!LV.setup){
    LV.setup = true;
    $("#lv-state").innerHTML = st.states.map(s => `<option value="${s.state}" ${s.state === st.state ? "selected" : ""}>${esc(s.name)}</option>`).join("");
    $("#lv-start").innerHTML = st.weeks.map((w, i) => `<option value="${i}">${fmtDate(w)}</option>`).join("");
    $("#lv-mistake").innerHTML = Object.entries(st.mistakes).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("#lv-next").onclick = () => { lvStop(); lvNext(); };
    $("#lv-play").onclick = lvPlay;
    $("#lv-restart").onclick = lvRestart;
    $("#lv-state").onchange = lvRestart;
    $("#lv-start").onchange = lvRestart;
    $("#lv-inject").onclick = async () => {
      try { const d = await lvApi(`inject?hospital_id=${encodeURIComponent($("#lv-hosp").value)}&mistake=${$("#lv-mistake").value}`, "POST"); lvPending(d.pending); }
      catch (e) { $("#lv-pending").textContent = e.message; }
    };
    $("#lv-tamper").onclick = () => showTab("audit");
  }
  await lvLoadState(st);
  // Hands-free demo and screenshots: ?steps=8&inject=lost_digit
  const q = new URLSearchParams(location.search);
  if (q.has("steps") && !LV.auto){
    LV.auto = true;
    if (q.has("inject")) { $("#lv-mistake").value = q.get("inject"); await $("#lv-inject").onclick(); }
    for (let i = 0; i < +q.get("steps"); i++) if (!(await lvNext())) break;
  }
}

// ---------------------------------------------------------------- shared map (Emergency, Early warning, Resources)
// pts: [{id, lat, lon, ...}]; opt: {color(h), radius(h), faded(h), ring(h), focus:Set|[], badges:{id:n},
//   lines:[{from,to,kind:"ray"|"arrow"|"dash"|"loan", w}], zoom:[ids], onPick(id), title(h)}
function geoMap(sel, pts, opt = {}){
  const el = $(sel);
  pts = pts.filter(h => h.lat != null && h.lon != null);
  if (!pts.length){ el.innerHTML = "<div class='empty'>No hospitals.</div>"; return {}; }
  const W = 640, H = 480, pad = 26;
  const zs = (opt.zoom || []).map(id => pts.find(h => h.id === id)).filter(Boolean);
  const box = zs.length >= 2 ? zs : pts;
  const lats = box.map(h => h.lat), lons = box.map(h => h.lon);
  const kx = Math.cos(((Math.min(...lats) + Math.max(...lats)) / 2) * Math.PI / 180);
  let x0 = Math.min(...lons) * kx, x1 = Math.max(...lons) * kx, y0 = Math.min(...lats), y1 = Math.max(...lats);
  if (zs.length >= 2){
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const half = Math.max(x1 - x0, (y1 - y0) * (W / H), 0.25) * 0.62;
    x0 = cx - half; x1 = cx + half; y0 = cy - half * H / W; y1 = cy + half * H / W;
  }
  const sc = Math.min((W - 2 * pad) / ((x1 - x0) || 1), (H - 2 * pad) / ((y1 - y0) || 1));
  const ox = (W - (x1 - x0) * sc) / 2, oy = (H - (y1 - y0) * sc) / 2;
  const pos = {};
  pts.forEach(h => { pos[h.id] = [ox + (h.lon * kx - x0) * sc, H - oy - (h.lat - y0) * sc]; });
  const focus = new Set(opt.focus || []);
  const mk = (id, c) => `<marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="${c}"/></marker>`;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img"><defs>${mk(sel.slice(1) + "-arr", css("--accent"))}${mk(sel.slice(1) + "-arr2", css("--green"))}</defs>
    <rect width="${W}" height="${H}" rx="10" fill="${css('--bg')}"/>`;
  (opt.lines || []).forEach(l => {
    const p = pos[l.from], q = pos[l.to]; if (!p || !q) return;
    const st = {ray: `stroke="${css('--c-coord')}" stroke-width="1.2" stroke-dasharray="3 4" opacity=".7"`,
                dash: `stroke="${css('--grey')}" stroke-width="1.2" stroke-dasharray="4 4" opacity=".7"`,
                arrow: `stroke="${css('--accent')}" stroke-width="${l.w || 3.5}" marker-end="url(#${sel.slice(1)}-arr)" opacity=".95"`,
                loan: `stroke="${css('--green')}" stroke-width="${l.w || 2.5}" marker-end="url(#${sel.slice(1)}-arr2)" opacity=".9"`}[l.kind || "ray"];
    s += `<line x1="${p[0].toFixed(1)}" y1="${p[1].toFixed(1)}" x2="${q[0].toFixed(1)}" y2="${q[1].toFixed(1)}" ${st}/>`;
  });
  pts.forEach(h => {
    const [x, y] = pos[h.id], f = focus.has(h.id), faded = opt.faded ? opt.faded(h) : false;
    const r = opt.radius ? opt.radius(h) : 6;
    if (opt.ring && opt.ring(h)) s += `<circle cx="${x}" cy="${y}" r="${r + 6}" fill="none" stroke="${css('--red')}" stroke-width="2.5" opacity=".85"/>`;
    s += `<circle data-id="${esc(h.id)}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="${opt.color ? opt.color(h) : css('--grey')}" fill-opacity="${faded ? .22 : .9}" stroke="${f ? css('--ink') : css('--panel')}" stroke-width="${f ? 3 : 1}"><title>${esc(opt.title ? opt.title(h) : h.name)}</title></circle>`;
  });
  Object.entries(opt.badges || {}).forEach(([id, n]) => {
    const p = pos[id]; if (!p) return;
    const bx = p[0] + 11, by = p[1] - 11;
    s += `<g><circle cx="${bx}" cy="${by}" r="10" fill="${css('--ink')}" stroke="${css('--panel')}" stroke-width="1.5"/><text x="${bx}" y="${by + 4}" text-anchor="middle" style="fill:${css('--panel')};font-size:12px;font-weight:700">${n}</text></g>`;
  });
  el.innerHTML = s + "</svg>";
  if (opt.onPick && el.querySelectorAll) el.querySelectorAll("circle[data-id]").forEach(c => c.addEventListener("click", () => opt.onPick(c.dataset.id)));
  return pos;
}
function badgeMap(items, extra){
  const b = {}; let n = 0;
  [...items.flatMap(it => it.focus || []), ...(extra || [])].forEach(id => { if (id && !(id in b) && n < 9) b[id] = ++n; });
  return b;
}
const bdgHtml = (b, ids) => (ids || []).filter(id => id in b).map(id => `<span class="bdg">${b[id]}</span>`).join("");
const provTag = k => `<span class="tag ${k}">${k}</span>`;
