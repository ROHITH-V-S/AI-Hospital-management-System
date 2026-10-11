"use strict";
// ---------------------------------------------------------------- STAFF & EQUIPMENT (weekly orchestration plan)
const RS = {setup: false, zoom: true, state: "AZ", week: "2023-11-19", plan: null, inv: null, show: {patients: true, staff: true, equipment: true}};

async function rsApi(path, method = "GET"){
  const r = await fetch("/api/resources/" + path, {method});
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
  return d;
}
function rsLines(list, kind, max){
  const tone = {patients: "--accent", staff: "--green", equipment: "--amber"}[kind];
  if (!list.length) return `<p class="small muted" style="margin:4px 0">Nothing to move this week.</p>`;
  const unit = x => kind === "patients" ? `about ${x.amount.toFixed(0)} patient${x.amount >= 1.5 ? "s" : ""}/day` : kind === "staff" ? `${x.amount} nurse${x.amount > 1 ? "s" : ""} per shift` : `${x.amount} × ${x.label.toLowerCase()}`;
  return list.slice(0, max).map(x => `<div class="item rs-line" data-from="${esc(x.from)}" data-to="${esc(x.to)}" style="border-left-color:${css(tone)};cursor:pointer" title="Click to show on the map"><b>${esc(unit(x))}</b>: ${esc(x.from_name)} → ${esc(x.to_name)}, ${x.km.toFixed(0)} km${x.warned ? ' <span class="pill AMBER">surge warning</span>' : ""}<div class="small muted">${esc(x.reason)}</div></div>`).join("") +
    (list.length > max ? `<p class="small muted">…and ${list.length - max} more (all saved when you make the plan).</p>` : "");
}
function rsDraw(){
  const p = RS.plan, ss = p.staff_summary, es = p.equipment_summary;
  const units = Object.values(es).reduce((a, x) => a + x.units_moved, 0);
  const sname = (RS.states.find(s => s.state === p.state) || {}).name || p.state;
  $("#rs-answer").textContent = `Week of ${fmtDate(p.week)} in ${sname}: ${p.patients.length} patient move${p.patients.length === 1 ? "" : "s"} suggested; ${ss.nurses_lent} nurse${ss.nurses_lent === 1 ? "" : "s"} per shift lent to cover ${ss.short_hospitals} hospital${ss.short_hospitals === 1 ? "" : "s"} estimated to be short; ${units} equipment unit${units === 1 ? "" : "s"} moved. ${p.warned_hospitals} hospitals are in a surge-warned area and are served first.`;
  $("#rs-patients").innerHTML = rsLines(p.patients.slice().sort((a, b) => b.amount - a.amount), "patients", 5);
  $("#rs-staff").innerHTML = `<p class="small" style="margin:0 0 6px">${ss.short_hospitals} hospital${ss.short_hospitals === 1 ? " is" : "s are"} estimated to be short of ${ss.nurses_short.toFixed(0)} nurse${ss.nurses_short === 1 ? "" : "s"} per shift; ${ss.nurses_lent} can be covered by nearby hospitals (within ${p.params.staff_radius_km} km).</p>` + rsLines(p.staff, "staff", 6);
  $("#rs-equip").innerHTML = `<table><tr><th>Item</th><th class="n">Hospitals short</th><th class="n">Units short</th><th class="n">Units moved</th></tr>${Object.values(es).map(x => `<tr><td>${esc(x.label)}</td><td class="n">${x.hospitals_short}</td><td class="n">${x.units_short}</td><td class="n">${x.units_moved}</td></tr>`).join("")}</table>` + rsLines(p.equipment, "equipment", 6);
  const lines = [
    ...(RS.show.patients ? p.patients.map(x => ({from: x.from, to: x.to, kind: "arrow", w: 1.5 + Math.min(4, x.amount / 3)})) : []),
    ...(RS.show.staff ? p.staff.map(x => ({from: x.from, to: x.to, kind: "loan", w: 2 + x.amount})) : []),
    ...(RS.show.equipment ? p.equipment.map(x => ({from: x.from, to: x.to, kind: "ray"})) : [])];
  const involved = new Set(lines.flatMap(l => [l.from, l.to]));
  geoMap("#rs-map", p.hospitals, {
    color: h => involved.has(h.id) ? css("--ink") : css("--grey"), radius: h => involved.has(h.id) ? 6 : 4,
    faded: h => !involved.has(h.id), ring: h => h.warned, lines,
    zoom: RS.focus ? RS.focus : RS.zoom ? [...involved] : [],
    focus: RS.focus || [], badges: RS.focus ? {[RS.focus[0]]: "A", [RS.focus[1]]: "B"} : {},
    title: h => `${h.name}${h.city ? " (" + h.city + ")" : ""}${h.warned ? " — in a surge-warned area" : ""}`});
  $("#rs-legend").innerHTML = ["patients", "staff", "equipment"].map(k => `<label style="display:inline-flex;gap:5px;align-items:center"><input type="checkbox" data-k="${k}" ${RS.show[k] ? "checked" : ""}><i style="background:var(${({patients: "--accent", staff: "--green", equipment: "--c-coord"})[k]})"></i>${({patients: "patients", staff: "nurses", equipment: "equipment (dashed)"})[k]}</label>`).join("") + `<span>◯ = surge-warned area</span>`;
  document.querySelectorAll("#rs-legend input").forEach(c => c.onchange = () => { RS.show[c.dataset.k] = c.checked; rsDraw(); });
  $("#rs-map-title").textContent = RS.focus ? `${p.hospitals.find(h => h.id === RS.focus[0])?.name || ""} (A) → ${p.hospitals.find(h => h.id === RS.focus[1])?.name || ""} (B)` : `${sname} · week of ${fmtDate(p.week)}`;
  document.querySelectorAll("#rs-root .rs-line").forEach(el => el.onclick = () => {
    const f = [el.dataset.from, el.dataset.to];
    RS.focus = RS.focus && RS.focus[0] === f[0] && RS.focus[1] === f[1] ? null : f; rsDraw();
  });
  $("#rs-zoom").innerHTML = `<span class="subnav" style="margin:0;display:inline-flex"><button data-z="1" aria-selected="${RS.zoom}">Where things move</button><button data-z="0" aria-selected="${!RS.zoom}">Whole state</button></span>`;
  document.querySelectorAll("#rs-zoom button").forEach(b => b.onclick = () => { RS.zoom = b.dataset.z === "1"; RS.focus = null; rsDraw(); });
}
async function rsInventory(){
  RS.inv = await rsApi(`inventory?state=${RS.state}`);
  const hs = [...new Map(RS.inv.map(r => [r.hospital, r.name])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  if (!RS.invHosp || !hs.some(h => h[0] === RS.invHosp)) RS.invHosp = hs.length ? hs[0][0] : null;
  $("#rs-inv-h").innerHTML = hs.map(([id, n]) => `<option value="${esc(id)}" ${id === RS.invHosp ? "selected" : ""}>${esc(n)}</option>`).join("");
  rsInvRows();
}
function rsInvRows(){
  const rows = RS.inv.filter(r => r.hospital === RS.invHosp);
  const label = {ventilator: "Ventilators", ecmo: "ECMO machines", dialysis: "Dialysis machines (ICU)", monitor: "Portable monitors"};
  $("#rs-inv").innerHTML = `<table><tr><th>Item</th><th class="n">Units</th><th>Entered by</th><th></th></tr>${rows.map(r => `<tr><td>${esc(label[r.item] || r.item)}</td><td class="n"><input type="number" min="0" max="10000" value="${r.units}" id="inv-${r.id}" style="width:80px"></td><td class="small muted">${esc(r.updated_by)}</td><td><button class="act" data-id="${r.id}">Save</button></td></tr>`).join("")}</table>`;
  document.querySelectorAll("#rs-inv button[data-id]").forEach(b => b.onclick = async () => {
    const id = b.dataset.id, v = +$("#inv-" + id).value;
    try { const d = await rsApi(`inventory?row_id=${id}&units=${v}`, "POST"); $("#rs-inv-msg").textContent = `Saved: ${d.before} → ${d.after}. Logged in the record book. The plan below is recomputed.`; await rsInventory(); await rsLoad(); }
    catch (e) { $("#rs-inv-msg").textContent = e.message; }
  });
}
async function rsLoad(){
  RS.focus = null;
  $("#rs-patients").innerHTML = $("#rs-staff").innerHTML = $("#rs-equip").innerHTML = `<div class="empty">Planning…</div>`;
  RS.plan = await rsApi(`plan?state=${RS.state}&week=${RS.week}`);
  rsDraw();
}
async function renderResources(){
  if (!RS.setup){
    $("#rs-root").innerHTML = `
      <div class="qa"><div class="q">This week: who should send patients, lend nurses or move equipment?</div><div class="a" id="rs-answer">…</div></div>
      <div class="card livebar"><div class="ctl">
        <label class="small muted" for="rs-state">State</label><select id="rs-state"></select>
        <label class="small muted" for="rs-week">Week</label><select id="rs-week"></select>
        <button class="act primary" id="rs-commit">Make this week's plan</button>
      </div><span class="small" id="rs-commit-msg"></span></div>
      <div class="banner sim"><b>Read the labels.</b> Patient numbers come from real reports ${provTag("observed")}. Staff per hospital is <b>estimated</b> ${provTag("estimated")} from its usual staffed beds and published nurse ratios — no public data reports staff per hospital. Equipment counts are <b>entered</b> ${provTag("entered")} (seeded with estimates; edit them below) — not public data. No research claim rests on equipment.</div>
      <div class="livegrid">
        <div>
          <div class="card"><h3>1 · Patients <span class="small muted">— the weekly transfer plan</span></h3><div id="rs-patients"></div></div>
          <div class="card" style="margin-top:12px"><h3>2 · Nurses <span class="small muted">— loans between nearby hospitals</span></h3><div id="rs-staff"></div></div>
          <div class="card" style="margin-top:12px"><h3>3 · Equipment <span class="small muted">— units moved to where they will be needed</span></h3><div id="rs-equip"></div></div>
        </div>
        <div class="card"><div class="maphead"><h3 id="rs-map-title">Plan</h3><span id="rs-zoom"></span></div>
          <div id="rs-map"></div><div class="legend" id="rs-legend"></div><p class="small muted" style="margin:6px 0 0">Arrows point to the hospital that receives. Click any line on the left to show just that move (click again to go back).</p></div>
      </div>
      <details class="card" style="margin-top:14px"><summary><b>Edit the equipment inventory</b> <span class="small muted">— what a state health department would enter</span></summary>
        <div class="controls" style="margin-top:10px"><label class="small muted" for="rs-inv-h">Hospital</label><select id="rs-inv-h"></select></div>
        <div id="rs-inv"></div><p class="small" id="rs-inv-msg" style="margin:6px 0 0"></p></details>
      <div class="not"><b>What this does not show</b><ul>
        <li id="rs-not-staff">…</li>
        <li>Lending nurses across hospitals needs contracts, credentials and willingness; the plan only says where it would help.</li>
        <li>Equipment counts and usage ratios are assumptions. Change a count and the plan changes — that is the point of the screen, not a finding.</li>
        <li>The patient plan is a suggestion checked against next week's real reports (see "This week").</li></ul></div>
      <div class="prov">Ratios: ICU 1 nurse : 2 patients, ward 1 : 5 (California Title 22) ${provTag("estimated")} · staff loans within 60 km, equipment within 100 km, surge-warned hospitals weighted ×1.5 ${provTag("derived")} · equipment ${provTag("entered")}</div>`;
    try {
      const sc = await get("staffing_check.json"), P = sc.periods["2020-08..2022-12"];
      $("#rs-not-staff").textContent = `Staff numbers are estimates. They only see one cause of shortage — more patients than the hospital's usual beds — not sick leave or vacancies. In 2020–22, ${pct(P.mean_real_share, 0)} of answering hospitals really reported a critical shortage in an average week, against ${pct(P.mean_est_share, 1)} flagged by our estimate (Evidence → 6).`;
    } catch (e) { $("#rs-not-staff").textContent = "Staff numbers are estimates (see Evidence → 6)."; }
    const w = await rsApi("weeks");
    RS.states = w.states;
    $("#rs-state").innerHTML = w.states.map(s => `<option value="${s.state}" ${s.state === RS.state ? "selected" : ""}>${esc(s.name)}</option>`).join("");
    if (!w.weeks.includes(RS.week)) RS.week = w.weeks[w.weeks.length - 1];
    $("#rs-week").innerHTML = w.weeks.map(x => `<option value="${x}" ${x === RS.week ? "selected" : ""}>${fmtDate(x)}</option>`).join("");
    $("#rs-state").onchange = async () => { RS.state = $("#rs-state").value; await rsLoad(); await rsInventory(); };
    $("#rs-week").onchange = async () => { RS.week = $("#rs-week").value; await rsLoad(); };
    $("#rs-inv-h").onchange = () => { RS.invHosp = $("#rs-inv-h").value; rsInvRows(); };
    $("#rs-commit").onclick = async () => {
      try { const d = await rsApi(`commit?state=${RS.state}&week=${RS.week}`, "POST"); $("#rs-commit-msg").innerHTML = `<span class="ok">✓ Saved ${d.lines} lines as record-book page #${d.id}.</span>`; }
      catch (e) { $("#rs-commit-msg").textContent = e.message; }
    };
    RS.setup = true;
  }
  await rsLoad();
  await rsInventory();
}
