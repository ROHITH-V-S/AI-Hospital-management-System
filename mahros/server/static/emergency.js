"use strict";
// ---------------------------------------------------------------- EMERGENCY (minutes)
const EM = {setup: false, zoomNear: true, state: "AZ", hs: [], byId: {}, origin: null, need: "icu", acuity: "critical",
            res: null, stage: -1, status: null, busy: false};
const EM_STEPS = [
  ["1 · Ask", "Request sent to all at once"],
  ["2 · Answers", "Each hospital decides"],
  ["3 · Check", "Data Steward checks bids"],
  ["4 · Choose", "Best bed chosen"],
  ["5 · Compare", "MAHROS vs phoning"]];

async function emApi(path, method = "GET"){
  const r = await fetch("/api/emergency/" + path, {method});
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
  return d;
}
function emOccColor(h){
  if (h.icu_occ == null) return css("--grey");
  return h.icu_occ >= 0.9 ? css("--red") : h.icu_occ >= 0.75 ? css("--amber") : css("--green");
}
function emSteps(){
  $("#em-steps").innerHTML = EM_STEPS.map(([n, t], i) =>
    `<li class="${i < EM.stage ? "done" : i === EM.stage ? "active" : ""}"><b>${n}</b>${t}</li>`).join("");
}
function emLegend(extra){
  $("#em-legend").innerHTML = `<span><i class="dot" style="background:var(--green)"></i>ICU under 75% full</span><span><i class="dot" style="background:var(--amber)"></i>75–90%</span><span><i class="dot" style="background:var(--red)"></i>over 90%</span><span><i class="dot" style="background:var(--grey)"></i>no ICU / no report</span>` + (extra || "");
  $("#em-legend").insertAdjacentHTML("beforeend", `<span class="muted">· dot colour = ICU fullness in this week's real report (a weekly average); the answers show beds free right now</span>`);
}
function kmBetween(a, b){
  const r = Math.PI / 180, dl = (b.lat - a.lat) * r, dn = (b.lon - a.lon) * r;
  const x = Math.sin(dl / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dn / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
}
function emNear(){
  const o = EM.byId[EM.origin];
  if (!o || !EM.zoomNear) return [];
  return EM.hs.filter(h => h.lat != null && kmBetween(o, h) <= 45).map(h => h.id);
}
function emZoomButtons(){
  $("#em-map-mode").innerHTML = `<span class="subnav" style="margin:0;display:inline-flex"><button data-z="1" aria-selected="${EM.zoomNear}">Around the patient</button><button data-z="0" aria-selected="${!EM.zoomNear}">Whole state</button></span>`;
  document.querySelectorAll("#em-map-mode button").forEach(b => b.onclick = () => { EM.zoomNear = b.dataset.z === "1"; EM.stage < 0 ? emIntro() : emShow(); });
}
function emBaseMap(opt = {}){
  const need = EM.need;
  geoMap("#em-map", EM.hs, Object.assign({
    color: emOccColor,
    radius: h => 4 + Math.sqrt(h.icu_beds || 4) / 1.6,
    faded: h => !h.can[need] && h.id !== EM.origin,
    title: h => `${h.name}${h.city ? " (" + h.city + ")" : ""} — ICU ${h.icu_occ == null ? "not reported" : pct(h.icu_occ, 0) + " full"} this week` + (h.can[need] ? "" : " — cannot treat this need"),
    onPick: id => { if (EM.stage < 0) { EM.origin = id; emIntro(); } },
    focus: EM.origin ? [EM.origin] : [],
    zoom: emNear(),
  }, opt));
  emZoomButtons();
}

// ---------------------------------------------------------------- intro / form
function emIntro(){
  EM.stage = -1; emSteps();
  const st = EM.status, o = EM.byId[EM.origin];
  const needOpts = Object.entries(st.needs).map(([k, v]) => `<option value="${k}" ${k === EM.need ? "selected" : ""}>${esc(v.label)} — within ${v.window} min</option>`).join("");
  const able = EM.hs.filter(h => h.can[EM.need]).length;
  $("#em-stage").innerHTML = `<div class="who" style="color:${css('--accent')}">Emergency transfer · ${esc(st.state_name)}</div>
    <h2>A patient needs a bed — now</h2>
    <p class="cap">A hospital has a patient it cannot treat (no specialist, or no free bed). Today staff phone other hospitals one by one. MAHROS asks every hospital that could help <b>at the same moment</b>, and each hospital's agent answers by itself.</p>
    <ol class="steps-howto">
      <li>Click the hospital where the patient is, on the map.</li>
      <li>Choose what the patient needs.</li>
      <li>Press <b>Find a bed</b>, then <b>Next step ›</b>.</li>
    </ol>
    <div class="form">
      <div class="pick ${o ? "set" : ""}">${o ? `Patient is at <b>${esc(o.name)}</b>${o.city ? ", " + esc(o.city) : ""}` : "No hospital picked yet — click one on the map"}</div>
      <div><label for="em-origin">…or choose the hospital from the list</label><select id="em-origin">${EM.hs.slice().sort((a, b) => a.name.localeCompare(b.name)).map(h => `<option value="${esc(h.id)}" ${h.id === EM.origin ? "selected" : ""}>${esc(h.name)}${h.city ? " — " + esc(h.city) : ""}</option>`).join("")}</select></div>
      <div><label for="em-need">The patient needs</label><select id="em-need">${needOpts}</select></div>
      <div><label for="em-acu">How urgent</label><select id="em-acu"><option value="critical" ${EM.acuity === "critical" ? "selected" : ""}>Critical — the full clinical window shown above</option><option value="serious" ${EM.acuity === "serious" ? "selected" : ""}>Serious — twice that window</option></select></div>
      <button class="act primary big" id="em-go" ${o ? "" : "disabled"}>Find a bed</button>
    </div>
    <p class="small muted" style="margin:6px 0 0">${able} of ${EM.hs.length} hospitals in ${esc(st.state_name)} can treat this (CMS records); the others are faded. ${esc(st.staffing)}</p>`;
  $("#em-need").onchange = e => { EM.need = e.target.value; emIntro(); };
  $("#em-origin").onchange = e => { EM.origin = e.target.value; emIntro(); };
  $("#em-acu").onchange = e => { EM.acuity = e.target.value; };
  $("#em-go").onclick = emFind;
  emBaseMap(); emLegend();
  $("#em-map-title").textContent = `${st.state_name} · ${EM.hs.length} hospitals`;
}

async function emFind(){
  if (EM.busy || !EM.origin) return;
  EM.busy = true; $("#em-go").disabled = true; $("#em-go").textContent = "Asking hospitals…";
  try {
    const r = await emApi(`find?state=${EM.state}&origin=${encodeURIComponent(EM.origin)}&need=${EM.need}&acuity=${EM.acuity}`, "POST");
    EM.res = r; EM.status = Object.assign(EM.status, r.status); EM.stage = 0;
    $("#em-clock").textContent = "Simulated clock: " + r.status.clock;
    emFeed(r); emShow();
  } catch (e) {
    $("#em-stage").insertAdjacentHTML("beforeend", `<p class="bad">${esc(e.message)}</p>`);
  } finally { EM.busy = false; }
}

// ---------------------------------------------------------------- the five steps
function emShow(){
  emSteps();
  const r = EM.res, k = EM.stage, o = r.origin.id;
  let title, cap, nums = [], items = [], extra = "", legendExtra = "", map = {};
  if (k === 0){
    title = `Request sent to ${r.asked_count} hospitals at once`;
    cap = `${r.origin.name} asks for: ${r.need_label.toLowerCase()} (${r.acuity}), at ${r.requested_at}. MAHROS sends the request at the same moment to every hospital that can treat this and can be reached in time.`;
    nums = [["hospitals asked", r.asked_count], ["clinical window", `${r.window_min.toFixed(0)} min`]];
    items = r.asked.slice().sort((a, b) => a.road_min - b.road_min).slice(0, 5).map(a => ({focus: [a.id], text: `${a.name} — ${a.road_min} min by road`}));
    if (r.asked_count > 5) items.push({text: `…and ${r.asked_count - 5} more.`});
    map = {lines: r.asked.map(a => ({from: o, to: a.id, kind: "ray"})), zoom: [o, ...r.asked.slice(0, 8).map(a => a.id)]};
  } else if (k === 1){
    const yes = r.asked.filter(a => a.yes), no = r.asked.filter(a => !a.yes);
    title = `${yes.length} said yes, ${no.length} said no`;
    cap = "Each hospital's agent checked its own beds, nurses on shift, equipment and its own reserve policy — information only that hospital has — and answered by itself, with a reason.";
    nums = [["yes", yes.length, "--green"], ["no", no.length, "--grey"]];
    items = [...yes.slice(0, 4).map(a => ({tone: "green", focus: [a.id], text: `Yes — ${a.name}: ${a.reason}. Answered ${a.answered_at}.`})),
             ...no.slice(0, 4).map(a => ({tone: "grey", focus: [a.id], text: `No — ${a.name}: ${a.reason}.`}))];
    map = {lines: r.asked.map(a => ({from: o, to: a.id, kind: a.yes ? "ray" : "dash"})),
           color: h => { const a = r.asked.find(x => x.id === h.id); return a ? (a.yes ? css("--green") : css("--grey")) : (h.id === o ? css("--accent") : emOccColor(h)); },
           zoom: [o, ...yes.slice(0, 6).map(a => a.id)]};
    legendExtra = `<span><i class="dot" style="background:var(--green)"></i>said yes</span><span><i class="dot" style="background:var(--grey)"></i>said no</span>`;
  } else if (k === 2){
    title = r.flags.length ? `${r.flags.length} bid${r.flags.length > 1 ? "s" : ""} need a quick check` : "Every bid matches the hospitals' own reports";
    cap = "The Data Steward compares each bid with what that hospital reported to the government this week. A bid that contradicts it is not thrown away — it must be confirmed by phone first, which costs time, so the coordinator counts that time when ranking.";
    nums = [["bids checked", r.yes_count], ["need a check", r.flags.length, r.flags.length ? "--amber" : "--ink"]];
    items = r.flags.length ? r.flags.map(f => ({tone: "miss", focus: [f.id], text: `${f.name}: ${f.why}.`}))
                           : [{tone: "green", text: "No bid contradicts its hospital's report this week."}];
    map = {ring: h => r.flags.some(f => f.id === h.id), zoom: [o, ...r.flags.map(f => f.id), ...r.asked.filter(a => a.yes).slice(0, 4).map(a => a.id)],
           color: h => { const a = r.asked.find(x => x.id === h.id); return a ? (a.yes ? css("--green") : css("--grey")) : emOccColor(h); }};
  } else if (k === 3){
    title = r.placed ? `Bed found: ${r.chosen.name}` : "No bed found";
    cap = r.placed
      ? `Chosen because the patient reaches definitive care soonest; ties go to the better-equipped hospital, then the one with more free beds. One doctor-to-doctor call confirmed it.`
      : "No hospital in reach could take this patient. The case is logged; in reality it would be escalated.";
    nums = r.placed ? [["time to bed", `${r.time_to_bed_min.toFixed(0)} min`, "--green"], ["drive", `${r.chosen.road_min} min`]] : [];
    items = r.ranking.slice(0, 3).map(x => ({tone: x.rank === 1 ? "green" : "", focus: [x.id], text: `#${x.rank} ${x.name}: ${x.why}.`}));
    if (r.placed) items.push({tone: r.within_window ? "green" : "miss", text: r.within_window ? `The patient reaches definitive care inside the ${r.window_min.toFixed(0)}-minute window.` : `Outside the ${r.window_min.toFixed(0)}-minute window — the nearest suitable bed is too far or not ready.`});
    map = r.placed ? {lines: [{from: o, to: r.chosen.id, kind: "arrow"}], zoom: [o, r.chosen.id, ...r.ranking.slice(1, 3).map(x => x.id)]} : {};
  } else {
    // Step 5: two timelines, in minutes from the request, using 10-minute calls.
    const p10 = r.phone["10"], lo = r.phone_range_min[0], hi = r.phone_range_min[1];
    const mins = r.time_to_bed_min, W = r.params.bid_window_min, C = r.params.call_min;
    const ph = p10 && p10.minutes != null ? p10.minutes : null;
    title = "MAHROS vs phoning one hospital at a time";
    cap = mins == null ? "MAHROS found no bed in reach at this moment."
        : ph == null ? `MAHROS found a bed in ${mins.toFixed(0)} minutes. Phoning one hospital at a time would not have found one.`
        : ph > mins + 0.5 ? `MAHROS found the bed ${(ph - mins).toFixed(0)} minutes sooner than phoning would have.`
        : `Here phoning would have been just as fast${ph < mins - 0.5 ? " (or faster)" : ""}: the nearest hospital had room, so the first call was enough. MAHROS helps most when the nearest hospitals are full.`;
    nums = [["MAHROS", mins == null ? "no bed" : `${mins.toFixed(0)} min`, "--green"],
            ["phoning", ph == null ? "no bed" : `${ph.toFixed(0)} min`, "--red"]];
    const clock = m => `${Math.floor(m)} min`;
    const acc = mins == null ? 0 : Math.max(1, Math.round((mins - W) / C));
    const mLines = mins == null ? [] : [
      `<li><b>${clock(0)}</b> — asks all ${r.asked_count} hospitals that can treat this, at the same moment.</li>`,
      `<li><b>${clock(W)}</b> — answers are in (MAHROS waits ${W} minutes for them).</li>`,
      `<li><b>${clock(mins)}</b> — ${acc > 1 ? `${acc} doctor-to-doctor calls` : "one doctor-to-doctor call"} (${C} minutes${acc > 1 ? " each" : ""}) confirm${acc > 1 ? "" : "s"} the bed at ${esc(r.chosen.name)}.</li>`];
    const pLines = p10 ? p10.call_list.map((c, i) => `<li><b>${clock((i + 1) * C)}</b> — call ${i + 1}: ${esc(c.name)} — ${c.yes ? "<b>yes</b>" : "no (" + esc(c.reason) + ")"}.</li>`) : [];
    extra = `<div class="grid g2" style="margin:4px 0 10px">
      <div class="card" style="border-left:4px solid ${css('--green')}"><h3>MAHROS — ${mins == null ? "no bed" : mins.toFixed(0) + " minutes"}</h3><ol class="small" style="margin:6px 0 0;padding-left:18px">${mLines.join("")}</ol></div>
      <div class="card" style="border-left:4px solid ${css('--red')}"><h3>Phoning, nearest first — ${ph == null ? "no bed" : ph.toFixed(0) + " minutes"}</h3><ol class="small" style="margin:6px 0 0;padding-left:18px">${pLines.join("") || "<li>No hospital in reach could take the patient.</li>"}</ol></div>
    </div>
    <p class="small muted" style="margin:0 0 8px">Both columns face the same hospitals at the same moment, and both end with a doctor-to-doctor call. We assume a phone call takes ${C} minutes (one study found about 12). ${lo != null && hi != null && hi > lo ? `If calls take 5 to 15 minutes, phoning would take ${lo.toFixed(0)} to ${hi.toFixed(0)} minutes.` : ""}</p>`;
    items = [];
    if (r.book) items.push({tone: "ledger", text: `Every message above is in the record book: page #${r.book.id} (${r.book.entries} lines). See the Audit log tab.`});
    map = p10 && p10.to_id ? {lines: [...(p10.call_list || []).map(c => ({from: o, to: c.id, kind: "dash"})), ...(r.placed ? [{from: o, to: r.chosen.id, kind: "arrow"}] : [])],
                              zoom: [o, ...(p10.call_list || []).map(c => c.id), ...(r.placed ? [r.chosen.id] : [])]} : {};
    legendExtra = `<span><i style="background:var(--accent)"></i>MAHROS: the bed chosen</span><span><i style="background:var(--grey)"></i>Phoning: hospitals called</span>`;
  }
  const b = badgeMap(items, []);
  const numsHtml = nums.map(([l, v, t]) => `<div><div class="v" style="color:${css(t || "--ink")}">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  const itemsHtml = items.map(it => `<div class="item" style="border-left-color:${css(TONE[it.tone] || "--line")}">${bdgHtml(b, it.focus)}${esc(it.text)}</div>`).join("");
  $("#em-stage").innerHTML = `<div class="who" style="color:${css(k === 2 ? '--c-stew' : k === 1 ? '--c-hosp' : '--c-coord')}">Step ${k + 1} of 5 · ${k === 1 ? "Hospital agents" : k === 2 ? "Data Steward agent" : k === 4 ? "Result" : "Emergency coordinator agent"}</div>
    <h2>${esc(title)}</h2><p class="cap">${esc(cap)}</p><div class="nums">${numsHtml}</div>${extra}${itemsHtml}
    <div class="controls" style="margin-top:12px">${k < 4 ? `<button class="act primary" id="em-next">Next step ›</button>` : `<button class="act primary" id="em-new">New patient</button>`}
      ${k > 0 ? `<button class="act" id="em-back">‹ Back</button>` : ""}</div>
    <p class="small muted" style="margin:6px 0 0">${esc(r.label)}</p>`;
  if ($("#em-next")) $("#em-next").onclick = () => { EM.stage += 1; emShow(); };
  if ($("#em-back")) $("#em-back").onclick = () => { EM.stage -= 1; emShow(); };
  if ($("#em-new")) $("#em-new").onclick = () => { emIntro(); };
  emBaseMap(Object.assign({badges: b, focus: [o, ...Object.keys(b)], onPick: null}, map));
  emLegend();
  if (legendExtra) $("#em-legend").innerHTML = legendExtra + `<span class="muted">· other dots: ICU fullness this week</span>`;
  $("#em-map-title").textContent = `${EM.status.state_name} · ${r.requested_at}` + ((map.zoom || []).length ? " · zoomed in" : "");
}
function emFeed(r){
  $("#em-feed").innerHTML = r.timeline.map(m => {
    const tone = m.kind === "DECLINE" ? "--grey" : m.kind === "BID" ? "--green" : m.kind === "STEWARD_FLAG" ? "--amber" : m.kind === "PLACED" ? "--accent" : "--line";
    return `<div class="ev" style="border-left-color:${css(tone)}"><span class="tag muted">${esc(m.at)} · ${esc(m.kind)}</span>${esc(m.who)} → ${esc(m.to)}: ${esc(m.text)}</div>`;
  }).join("");
}

// ---------------------------------------------------------------- loading
async function emLoad(state, reset){
  EM.state = state;
  const st = reset ? await emApi(`reset?state=${state}&week=${$("#em-week").value}`, "POST") : await emApi(`status?state=${state}`);
  EM.status = st;
  EM.hs = await emApi(`hospitals?state=${state}`);
  EM.byId = Object.fromEntries(EM.hs.map(h => [h.id, h]));
  if (!EM.byId[EM.origin]){
    // Suggest a small hospital with an emergency department and no cath lab: a typical sender.
    const cand = EM.hs.filter(h => h.ed_visits_week && !h.can.cath_lab && h.lat).sort((a, b) => (b.ed_visits_week || 0) - (a.ed_visits_week || 0));
    EM.origin = cand.length ? cand[0].id : null;
  }
  const busiest = st.weeks.reduce((a, w) => w.icu_occupancy > a.icu_occupancy ? w : a, st.weeks[0]);
  $("#em-week").innerHTML = st.weeks.map(w => `<option value="${w.week}" ${w.week === st.week ? "selected" : ""}>${fmtDate(w.week)} · ICUs ${pct(w.icu_occupancy, 0)} full${w.week === busiest.week ? " (busiest)" : ""}</option>`).join("");
  $("#em-clock").textContent = "Simulated clock: " + st.clock;
  $("#em-prov").innerHTML = `Where the numbers come from: hospitals, ICU beds and patients ${provTag("observed")} (HHS weekly report) · what each hospital can treat ${provTag("observed")} (CMS Provider of Services) · road times ${provTag("observed")} (OpenStreetMap / OSRM) · nurses on shift ${provTag("estimated")} (ICU 1 nurse : 2 patients) · minute-by-minute beds, patients, answers ${provTag("simulated")} · data read from: ${esc(st.data_source || "")}`;
  emIntro();
}
async function renderEmergency(){
  let st;
  try { st = await emApi("status"); } catch (e) { st = {ready: false, error: e.message}; }
  if (!st.ready){
    $("#em-main").style.display = "none"; $("#em-wait").style.display = "block";
    $("#em-wait").innerHTML = st.error
      ? `<div class="q">Emergency</div><div class="a">The emergency module is not available here.</div><p class="small muted">${esc(st.error)}</p>`
      : `<div class="q">Emergency</div><div class="a">Loading the hospitals of Arizona and Massachusetts…</div><p class="small muted">A few seconds after the server starts.</p>`;
    if (!st.error) setTimeout(renderEmergency, 1500);
    return;
  }
  $("#em-wait").style.display = "none"; $("#em-main").style.display = "block";
  if (!EM.setup){
    EM.setup = true;
    $("#em-state").innerHTML = st.states.map(s => `<option value="${s.state}">${esc(s.name)}</option>`).join("");
    $("#em-state").onchange = () => { EM.origin = null; emLoad($("#em-state").value, false); };
    $("#em-week").onchange = () => emLoad(EM.state, true);
    $("#em-restart").onclick = () => emLoad(EM.state, true);
  }
  await emLoad(EM.state, false);
  // Hands-free demo / screenshots: ?em=cath_lab&steps=4
  const q = new URLSearchParams(location.search);
  if (q.has("em") && !EM.auto){
    EM.auto = true; EM.need = q.get("em"); emIntro();
    await emFind();
    for (let i = 0; i < +(q.get("steps") || 0); i++){ EM.stage = Math.min(4, EM.stage + 1); emShow(); }
  }
}
