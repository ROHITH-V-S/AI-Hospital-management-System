"use strict";
// ---------------------------------------------------------------- EARLY WARNING (real weekly reports)
const EW = {setup: false, state: "AZ", week: null, reveal: false, data: null, thr: 0.23};
const STATE_LIST = {AL:"Alabama",AK:"Alaska",AZ:"Arizona",AR:"Arkansas",CA:"California",CO:"Colorado",CT:"Connecticut",DE:"Delaware",DC:"District of Columbia",FL:"Florida",GA:"Georgia",HI:"Hawaii",ID:"Idaho",IL:"Illinois",IN:"Indiana",IA:"Iowa",KS:"Kansas",KY:"Kentucky",LA:"Louisiana",ME:"Maine",MD:"Maryland",MA:"Massachusetts",MI:"Michigan",MN:"Minnesota",MS:"Mississippi",MO:"Missouri",MT:"Montana",NE:"Nebraska",NV:"Nevada",NH:"New Hampshire",NJ:"New Jersey",NM:"New Mexico",NY:"New York",NC:"North Carolina",ND:"North Dakota",OH:"Ohio",OK:"Oklahoma",OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",SC:"South Carolina",SD:"South Dakota",TN:"Tennessee",TX:"Texas",UT:"Utah",VT:"Vermont",VA:"Virginia",WA:"Washington",WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming"};
const TEST_START = "2023-01-01";

async function ewApi(path){
  const r = await fetch("/api/warning" + path);
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
  return d;
}
function ewColor(h){
  if (EW.reveal){
    if (h.next_peak == null) return css("--grey");
    return h.next_peak >= 0.85 ? css("--red") : css("--green");
  }
  if (h.p == null) return css("--grey");
  return h.p >= EW.thr ? css("--red") : h.p >= 0.10 ? css("--amber") : css("--green");
}
function ewDraw(){
  const d = EW.data, warn = d.alerts.filter(a => a.kind === "warning" && a.rule === "model"),
        already = d.alerts.filter(a => a.kind === "already" && a.rule === "model");
  const hit = warn.filter(a => a.happened === true).length, known = warn.filter(a => a.happened != null).length;
  const sname = STATE_LIST[d.state] || d.state;
  const isTest = d.week >= TEST_START;
  $("#ew-answer").textContent = warn.length
    ? `In the week of ${fmtDate(d.week)}, MAHROS warned ${warn.length} ${sname} area${warn.length > 1 ? "s" : ""} that ${warn.length > 1 ? "were" : "was"} still below ${pct(d.threshold, 0)} full but likely to cross it within 2 weeks. ${already.length} other area${already.length === 1 ? " was" : "s were"} already over ${pct(d.threshold, 0)}.`
    : `In the week of ${fmtDate(d.week)}, no ${sname} area below ${pct(d.threshold, 0)} was warned. ${already.length} area${already.length === 1 ? " was" : "s were"} already over ${pct(d.threshold, 0)}.`;
  const b = badgeMap(warn.map(a => ({focus: [a.id]})), []);
  const item = (a, tone) => `<div class="item" style="border-left-color:${css(TONE[tone])}">${bdgHtml(b, [a.id])}<b>${esc(a.area)}</b> (around ${esc(nicePk(a.name))}): ${esc(a.message)}` +
    (EW.reveal && a.happened != null ? ` <span class="pill ${a.happened ? "RED" : "GREEN"}">${a.happened ? "it did reach " + pct(d.threshold, 0) : "it did not"}</span>` : "") + `</div>`;
  $("#ew-list").innerHTML =
    `<h3 style="margin:0 0 6px">Warnings — still below ${pct(d.threshold, 0)}, likely to cross within 2 weeks</h3>` +
    (warn.length ? warn.map(a => item(a, "amber")).join("") : `<p class="muted small">None this week.</p>`) +
    (EW.reveal && known ? `<p class="small" style="margin:6px 0 10px"><b>${hit} of ${known}</b> warnings came true.</p>` : "") +
    `<details style="margin-top:12px"><summary class="small"><b>${already.length}</b> area${already.length === 1 ? "" : "s"} already over ${pct(d.threshold, 0)} (status, not a warning)</summary>${already.slice(0, 15).map(a => item(a, "red")).join("")}${already.length > 15 ? `<p class="small muted">…and ${already.length - 15} more.</p>` : ""}</details>`;
  geoMap("#ew-map", d.hospitals, {
    color: ewColor, radius: h => 3.5 + Math.sqrt(h.n || 1) * 1.1,
    ring: h => warn.some(a => a.id === h.id), badges: b, focus: Object.keys(b),
    title: h => `${nicePk(h.name)} area (${h.n} hospitals within 50 km): ${h.area_occ == null ? "no trusted report" : pct(h.area_occ, 0) + " full"}` +
      (h.p != null ? `; chance of ${pct(d.threshold, 0)} within 2 weeks ${pct(h.p, 0)}` : "") + (EW.reveal && h.next_peak != null ? `; really reached ${pct(h.next_peak, 0)}` : "")});
  $("#ew-legend").innerHTML = EW.reveal
    ? `<span><i class="dot" style="background:var(--red)"></i>really reached ${pct(d.threshold, 0)} within 2 weeks</span><span><i class="dot" style="background:var(--green)"></i>did not</span><span>◯ = warned</span>`
    : `<span><i class="dot" style="background:var(--green)"></i>chance under 10%</span><span><i class="dot" style="background:var(--amber)"></i>10% to ${pct(EW.thr, 0)}</span><span><i class="dot" style="background:var(--red)"></i>${pct(EW.thr, 0)} or more (warning level)</span><span>◯ = warned area</span>`;
  $("#ew-map-title").textContent = `${sname} · week of ${fmtDate(d.week)}`;
  $("#ew-mode").innerHTML = isTest ? `<span class="pill GREEN">test week — never seen in training</span>` : `<span class="pill AMBER">calibration week — used to set the alarm level</span>`;
}
const nicePk = n => String(n || "").toLowerCase().replace(/\b[a-z]/g, c => c.toUpperCase());
async function ewLoad(){
  EW.data = await ewApi(`?state=${EW.state}&week=${EW.week}`);
  ewDraw();
}
async function renderWarning(){
  if (!EW.setup){
    $("#ew-root").innerHTML = `
      <div class="qa"><div class="q">Will hospitals near here be too full in 1–2 weeks?</div><div class="a" id="ew-answer">…</div></div>
      <div class="card livebar"><div class="ctl">
        <label class="small muted" for="ew-state">State</label><select id="ew-state"></select>
        <label class="small muted" for="ew-week">Week</label><select id="ew-week"></select>
        <label class="small" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="ew-reveal"> Show what really happened 2 weeks later</label>
      </div><span id="ew-mode"></span></div>
      <div class="banner real"><b>Real data.</b> Every number is from hospitals' real weekly reports. An "area" is a hospital and every hospital within 50 km. The warning comes from a model trained on 2020–2022; from January 2023 on, the weeks were never seen in training. This is a <b>surge early warning</b> for hospital capacity — not a pandemic or outbreak prediction.</div>
      <div class="livegrid">
        <div class="card" id="ew-list"></div>
        <div class="card"><div class="maphead"><h3 id="ew-map-title">Areas</h3><span class="small muted">Each dot = one area, centred on a hospital</span></div>
          <div id="ew-map"></div><div class="legend" id="ew-legend"></div></div>
      </div>
      <p class="small" style="margin:12px 0 0">Warnings feed the planner on the <a href="#" id="ew-to-res">Staff &amp; equipment</a> tab: hospitals in a warned area are first in line for loaned nurses and equipment. How good the warnings are, measured over 2023–24: <a href="#" id="ew-to-ev">Evidence → 5</a>.</p>
      <div class="not"><b>What this does not show</b><ul>
        <li id="ew-not-lead">…</li>
        <li>Symptom-level data (CDC syndromic surveillance) is not public, so this cannot see an outbreak before it reaches hospitals.</li>
        <li>Emergency-department visits stopped being required on 11 June 2023, so many hospitals stopped sending them; the warning works without them.</li>
        <li>Areas overlap: one busy city shows up as many dots. Warnings close together are merged into one.</li></ul></div>
      <div class="prov">Where the numbers come from: occupancy, admissions, ED visits ${provTag("observed")} (HHS weekly reports) · area totals, trends, chance of crossing ${provTag("derived")} (experiments/surge_warning.py)</div>`;
    const ev = await get("surge_warning.json");
    EW.thr = ev.methods.model.threshold;
    const L = ev.methods.model.lead, M = ev.methods.model.test_onset;
    $("#ew-not-lead").textContent = `In testing (2023–24), ${pct(L.warned_1_week_or_more, 0)} of real surges were warned at least a week ahead and ${pct(L.missed, 0)} came with no warning; ${pct(M.precision, 0)} of warnings came true. See Evidence → 5 for the named misses.`;
    $("#ew-state").innerHTML = Object.entries(STATE_LIST).sort((a, b) => a[1].localeCompare(b[1])).map(([k, v]) => `<option value="${k}" ${k === EW.state ? "selected" : ""}>${esc(v)}</option>`).join("");
    $("#ew-state").onchange = async () => { EW.state = $("#ew-state").value; await ewWeeks(); await ewLoad(); };
    $("#ew-week").onchange = async () => { EW.week = $("#ew-week").value; await ewLoad(); };
    $("#ew-reveal").onchange = () => { EW.reveal = $("#ew-reveal").checked; ewDraw(); };
    $("#ew-to-res").onclick = e => { e.preventDefault(); showTab("resources"); };
    $("#ew-to-ev").onclick = e => { e.preventDefault(); showTab("evidence"); showSub("ev_warning"); };
    EW.setup = true;
    if (new URLSearchParams(location.search).get("reveal")) { EW.reveal = true; $("#ew-reveal").checked = true; }
  }
  await ewWeeks();
  await ewLoad();
}
async function ewWeeks(){
  const w = (await ewApi(`/weeks?state=${EW.state}`)).weeks;
  if (!w.some(x => x.week === EW.week)){
    // Start on the test week with the most warnings, so there is something to see.
    const test = w.filter(x => x.week >= TEST_START);
    EW.week = (test.length ? test : w).reduce((a, x) => x.warnings > a.warnings ? x : a).week;
  }
  $("#ew-week").innerHTML = w.map(x => `<option value="${x.week}" ${x.week === EW.week ? "selected" : ""}>${fmtDate(x.week)} · ${x.warnings} warning${x.warnings === 1 ? "" : "s"}${x.week < TEST_START ? " (calibration)" : ""}</option>`).join("");
}
