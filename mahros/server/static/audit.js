"use strict";
// ---------------------------------------------------------------- AUDIT LOG (record book in the database)
const AU = {setup: false};
async function auApi(path, method = "GET"){
  const r = await fetch("/api/book" + path, {method});
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
  return d;
}
function auVerify(v, tampered){
  const el = $("#au-verify");
  if (v.ok){
    el.className = "verify ok";
    el.innerHTML = `✓ Nothing has been changed. ${esc(v.message)}`;
  } else {
    el.className = "verify bad";
    el.innerHTML = `✗ Something was changed after it was written.<br><span style="font-weight:500;font-size:14.5px">${esc(v.message)}</span>` +
      (tampered ? `<br><span style="font-weight:500;font-size:13.5px">(This was the one-click demo: it changed bid #${tampered.row_id}'s travel time from ${tampered.before} to ${tampered.after} minutes directly in the database. Press "Undo my change".)</span>` : "");
  }
}
function auBodyText(e){
  const b = e.body || {};
  const parts = [];
  if (b.need) parts.push(`need ${b.need}`);
  if (b.reason) parts.push(b.reason);
  if (b.travel_min != null) parts.push(`${b.travel_min} min away`);
  if (b.time_to_bed_min != null) parts.push(`bed in ${b.time_to_bed_min} min`);
  if (b.patients_per_day != null) parts.push(`${b.patients_per_day} patients/day`);
  if (b.why) parts.push(b.why);
  if (b.level) parts.push(b.level);
  if (b.used != null) parts.push(`${b.used} patients, ${b.beds} beds`);
  return parts.join(" · ").slice(0, 150);
}
function auLines(lines){
  $("#au-lines").innerHTML = lines.length ? lines.map(e => `<div class="bookline"><span class="k">#${e.seq} ${esc(e.kind)}</span> <span class="muted">${esc(e.recorded_at.replace("T", " "))}</span> · ${esc(e.sender)} → ${esc(e.receiver)}${auBodyText(e) ? " · " + esc(auBodyText(e)) : ""}
      <div class="hash muted">fingerprint ${esc(e.hash.slice(0, 24))}… · previous ${esc(e.prev_hash.slice(0, 12))}…</div></div>`).join("")
    : `<p class="muted">The book is empty. Find a bed on the Emergency tab, or run a week on "This week".</p>`;
}
function auPages(pages){
  $("#au-pages").innerHTML = pages.length ? pages.map(p => `<div class="prop"><b>Page ${p.id}</b> · ${esc(p.label)} · lines ${p.first_seq ?? "–"}–${p.last_seq ?? "–"} ${p.sealed ? "· sealed" : "· being written"}<div class="hash muted">${esc(p.hash || "")}</div></div>`).join("")
    : `<p class="muted">No pages yet.</p>`;
}
async function renderAudit(){
  if (!AU.setup){
    AU.setup = true;
    $("#au-check").onclick = async () => { try { auVerify(await auApi("/verify", "POST"), AU.t); } catch (e) { $("#au-verify").textContent = e.message; } };
    $("#au-tamper").onclick = async () => {
      try { const d = await auApi("/tamper", "POST"); AU.t = d.tampered; auVerify(d.verify, d.tampered); }
      catch (e) { $("#au-verify").className = "verify bad"; $("#au-verify").textContent = e.message; }
    };
    $("#au-undo").onclick = async () => { const d = await auApi("/undo", "POST"); AU.t = null; auVerify(d.verify); };
  }
  try {
    const d = await auApi("?limit=40");
    AU.t = d.demo_tamper;
    auVerify(d.verify, d.demo_tamper);
    auLines(d.recent); auPages(d.blocks);
    $("#au-db").textContent = `Stored in the ${d.database === "postgresql" ? "PostgreSQL" : d.database} database: ${num(d.summary.entries)} lines on ${num(d.summary.blocks)} pages.`;
  } catch (e) {
    $("#au-verify").className = "verify bad"; $("#au-verify").textContent = "Database not available: " + e.message;
  }
  try { await renderResearchLedger(); } catch (e) { $("#au-status").textContent = "Research log not built."; }
}
