"use strict";
// ---------------------------------------------------------------- DATA TRUST (the Steward's verdicts, live from the database)
const DT = {setup: false, state: "AZ", week: "2023-11-19"};
async function dtApi(path){
  const r = await fetch("/api/" + path);
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
  return d;
}
async function dtLoad(){
  const d = await dtApi(`trust?state=${DT.state}&week=${DT.week}`);
  const c = d.counts, total = Object.values(c).reduce((a, b) => a + b, 0);
  const sname = (DT.states.find(s => s.state === d.state) || {}).name || d.state;
  $("#dt-answer").textContent = `Week of ${fmtDate(d.week)}: of ${total} ${sname} hospitals, ${c.RED || 0} sent a report that cannot be right and ${c.MISSING || 0} sent nothing usable. Those reports are not used to send anyone patients; the hospitals can still be helped, judged on their earlier trusted reports.`;
  const lv = [["GREEN", "Usable as reported"], ["AMBER", "Usable, minor issue"], ["RED", "Cannot be right — set aside"], ["MISSING", "Nothing usable"]];
  $("#dt-levels").innerHTML = lv.map(([k, t]) => `<div class="card"><span class="pill ${k}">${k}</span><div class="big">${c[k] || 0}</div><div class="small muted">${t}</div></div>`).join("");
  const red = d.flagged.filter(x => x.level === "RED"), amber = d.flagged.filter(x => x.level === "AMBER");
  const item = x => `<div class="item" style="border-left-color:${css(x.level === "RED" ? "--red" : "--amber")}"><b>${esc(x.name)}</b>${x.city ? ", " + esc(x.city) : ""} — reported ${x.used == null ? "–" : num(x.used, 1)} patients and ${x.beds == null ? "–" : num(x.beds, 1)} beds: ${esc(x.why.join("; "))}.</div>`;
  $("#dt-list").innerHTML = (red.length ? red.map(item).join("") : `<p class="muted small">No report was set aside this week.</p>`) +
    (amber.length ? `<details style="margin-top:8px"><summary class="small">${amber.length} report${amber.length > 1 ? "s" : ""} with a minor issue (still used)</summary>${amber.map(item).join("")}</details>` : "");
  const bids = await dtApi("trust/bids?limit=12");
  $("#dt-bids").innerHTML = bids.length ? bids.map(b => `<div class="item" style="border-left-color:${css("--amber")}"><b>${esc(b.name)}</b> (${esc(b.state)}, simulated ${esc(String(b.at).replace("T", " "))}, request #${b.request}): ${esc(b.note)}.</div>`).join("")
    : `<p class="muted small">No emergency bid has been flagged yet. Find beds on the Emergency tab; a bid from a hospital whose own report says its ICU is full is flagged for a phone check.</p>`;
}
async function renderDataTrust(){
  if (!DT.setup){
    $("#dt-root").innerHTML = `
      <div class="qa"><div class="q">Which hospital reports can we not trust this week — and why?</div><div class="a" id="dt-answer">…</div></div>
      <div class="card livebar"><div class="ctl">
        <label class="small muted" for="dt-state">State</label><select id="dt-state"></select>
        <label class="small muted" for="dt-week">Week</label><select id="dt-week"></select>
      </div></div>
      <div class="banner real"><b>Real data.</b> These are the Data Steward agent's verdicts on the hospitals' real weekly reports, read from the database. Each one names the rule that fired.</div>
      <div class="grid g4" id="dt-levels"></div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h3>Reports set aside this week</h3><div id="dt-list" class="list"></div></div>
        <div class="card"><h3>Emergency bids the Steward asked to confirm</h3><p class="small muted" style="margin:0 0 8px">A bid that contradicts the hospital's own weekly report (for example, offering an ICU bed while reporting its ICU 100% full) is not thrown away; it is confirmed by phone first.</p><div id="dt-bids" class="list"></div></div>
      </div>
      <p class="small" style="margin:12px 0 0">How often reports are wrong across the whole country, and how we know the flags are real: <a href="#" id="dt-to-ev">Evidence → 1</a>. Try adding a mistake yourself on <a href="#" id="dt-to-live">This week</a>.</p>
      <div class="not"><b>What this does not show</b><ul>
        <li>RED means "very unlikely to be a real measurement", not "the hospital lied". Most causes are technical: a feed that stopped updating, a typo.</li>
        <li>Small, steady errors (a count 10% too high) are mostly not caught — see the planted-error table in Evidence → 1.</li>
        <li>A flagged emergency bid is a reason to phone, not an accusation; in the simulation hospitals always answer honestly.</li></ul></div>
      <div class="prov">Reports ${provTag("observed")} (HHS) · verdicts ${provTag("derived")} (mahros/trust/checks.py) · emergency bids ${provTag("simulated")}</div>`;
    const w = await dtApi("resources/weeks");
    DT.states = w.states;
    $("#dt-state").innerHTML = w.states.map(s => `<option value="${s.state}" ${s.state === DT.state ? "selected" : ""}>${esc(s.name)}</option>`).join("");
    if (!w.weeks.includes(DT.week)) DT.week = w.weeks[w.weeks.length - 1];
    $("#dt-week").innerHTML = w.weeks.map(x => `<option value="${x}" ${x === DT.week ? "selected" : ""}>${fmtDate(x)}</option>`).join("");
    $("#dt-state").onchange = () => { DT.state = $("#dt-state").value; dtLoad(); };
    $("#dt-week").onchange = () => { DT.week = $("#dt-week").value; dtLoad(); };
    $("#dt-to-ev").onclick = e => { e.preventDefault(); showTab("evidence"); showSub("trust"); };
    $("#dt-to-live").onclick = e => { e.preventDefault(); showTab("live"); };
    DT.setup = true;
  }
  await dtLoad();
}
