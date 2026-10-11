// Headless smoke test for the dashboard page.
//
//   node tests/ui_smoke.js            (after experiments/build_ui_data.py)
//
// Runs every tab's render code against the real files in results/ui/ with a
// minimal fake DOM, and fails on any runtime error or any "undefined"/"NaN"
// that reaches the page. It does not check layout -- only that every number
// the page tries to show actually exists in the results.

const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "mahros/server/static/index.html"), "utf8");
// Every script the page loads, in order, except boot.js (which starts the page).
const files = [...html.matchAll(/<script src="\/static\/([a-z_]+\.js)"><\/script>/g)].map(m => m[1]).filter(f => f !== "boot.js");
const js = files.map(f => fs.readFileSync(path.join(ROOT, "mahros/server/static", f), "utf8")).join("\n");
const UI = path.join(ROOT, "results/ui");

const written = {};
function el(id) {
  const o = {
    id, _html: "", _text: "", value: "0", options: [], dataset: {}, style: {}, classList: { toggle() {} },
    set innerHTML(v) { this._html = String(v); written[id] = this._html;
      const m = this._html.match(/<option[^>]*value="([^"]*)"/); if (m && (this.value === "0" || !this.value)) this.value = m[1];
      this.options = (this._html.match(/<option/g) || []); },
    get innerHTML() { return this._html; },
    set textContent(v) { this._text = String(v); written[id] = this._text; },
    get textContent() { return this._text; },
    insertAdjacentHTML(_, v) { written[id + ":error"] = v; },
    setAttribute() {}, addEventListener() {}, click() {},
    set onchange(f) { this._onchange = f; }, set onclick(f) { this._onclick = f; },
  };
  return o;
}
const els = {};
global.document = {
  querySelector(s) { const id = s.replace(/^#/, ""); return els[id] || (els[id] = el(id)); },
  querySelectorAll() { return []; },
  getElementById(id) { return this.querySelector("#" + id); },
  documentElement: {},
};
global.getComputedStyle = () => ({ getPropertyValue: () => "#000" });
global.localStorage = { getItem: () => null, setItem() {} };
global.location = { search: "" };
global.fetch = async (url, opt) => {
  if (url.startsWith("/ui/")) {
    const p = path.join(UI, url.slice(4));
    if (!fs.existsSync(p)) return { ok: false, status: 404 };
    const data = JSON.parse(fs.readFileSync(p, "utf8"));
    return { ok: true, json: async () => data };
  }
  if (url.startsWith("/api/live/status")) {
    // The live console needs the local data cache; here we check it degrades cleanly.
    return { ok: true, json: async () => ({ ready: false, loading: false, error: "no data cache in smoke test" }) };
  }
  if (url.startsWith("/api/warning/weeks")) {
    return { ok: true, json: async () => ({ state: "AZ", weeks: [{ week: "2023-11-19", warnings: 1 }, { week: "2022-12-04", warnings: 0 }] }) };
  }
  if (url.startsWith("/api/warning")) {
    return { ok: true, json: async () => ({ state: "AZ", week: "2023-11-19", threshold: 0.85, radius_km: 50,
      hospitals: [{ id: "1", name: "A", city: "X", lat: 33.4, lon: -112, area_occ: 0.83, d2: -0.01, p: 0.79, n: 8, rising: 1, next_peak: 0.87 },
                  { id: "2", name: "B", city: "Y", lat: 32.2, lon: -110.9, area_occ: 0.9, d2: 0.0, p: 0.95, n: 7, rising: 0, next_peak: null }],
      alerts: [{ id: "1", rule: "model", p: 0.79, name: "A", city: "X", area: "X area", message: "83% full now.", area_occ: 0.83, kind: "warning", happened: true },
               { id: "2", rule: "model", p: 0.95, name: "B", city: "Y", area: "Y area", message: "90% full now.", area_occ: 0.9, kind: "already", happened: null }] }) };
  }
  if (url.startsWith("/api/emergency/status")) {
    return { ok: true, json: async () => ({ ready: false, loading: false, error: "no data cache in smoke test" }) };
  }
  if (url.startsWith("/api/book")) {
    return { ok: true, json: async () => ({
      summary: { entries: 3, blocks: 1, head: "ab".repeat(32) }, database: "postgresql",
      verify: { ok: true, entries: 3, message: "All 3 lines match." }, demo_tamper: null,
      recent: [{ seq: 1, kind: "BID", recorded_at: "2024-01-08T10:42:00", sender: "hospital:1", receiver: "coordinator",
                 body: { reason: "3 ICU beds free", travel_min: 14 }, hash: "cd".repeat(32), prev_hash: "0".repeat(64) }],
      blocks: [{ id: 1, label: "Emergency · Arizona", first_seq: 1, last_seq: 3, sealed: true, hash: "ef".repeat(32) }] }) };
  }
  if (url.startsWith("/api/ledger")) {
    const idx = JSON.parse(fs.readFileSync(path.join(UI, "index.json"), "utf8"));
    const tam = url.includes("tamper");
    return { ok: true, json: async () => ({
      verify: tam ? { ok: false, first_bad_block: 3, label: "X" } : { ...idx.ledger.verify },
      published_head: idx.ledger.verify.head, rebuilt_matches_published: !tam,
      tampered: tam ? { hospital: "hospital:1", before: 10, after: 5 } : null,
      blocks: idx.ledger.blocks }) };
  }
  throw new Error("unexpected fetch " + url);
};

(async () => {
  const names = ["renderLive", "renderOverview", "renderTrust", "renderForecast", "renderCoord", "drawWeek",
                 "renderAudit", "renderEmergency", "renderEvEmergency", "renderWarning", "renderEvWarning",
                 "renderResources", "renderEvStaff", "renderDataTrust"];
  const run = new Function(js + "\nreturn {" + names.map(n => `${n}: typeof ${n} === "function" ? ${n} : undefined`).join(",") + "};");
  const R = run();
  const errors = [];
  for (const [name, f] of Object.entries(R)) {
    if (!f) { console.log(`note: ${name} not defined yet`); continue; }
    try { await f(); } catch (e) { errors.push(`${name}: ${e.stack || e}`); }
  }
  // Exercise every week x a few states in the explorer.
  const idx = JSON.parse(fs.readFileSync(path.join(UI, "index.json"), "utf8"));
  for (const w of idx.weeks) for (const s of idx.states.slice(0, 60)) {
    document.querySelector("#co-week").value = w.week;
    document.querySelector("#co-state").value = s;
    try { await R.drawWeek(); } catch (e) { errors.push(`drawWeek ${w.week} ${s}: ${e}`); }
  }
  for (const [id, v] of Object.entries(written)) {
    if (/undefined|NaN|\[object Object\]/.test(v)) errors.push(`#${id} shows a broken value: ` +
      v.match(/.{0,60}(undefined|NaN|\[object Object\]).{0,40}/)[0]);
    if (id.endsWith(":error")) errors.push(`#${id}: ${v.slice(0, 200)}`);
  }
  // A missing number renders as "–". Some are legitimate (a state with nothing
  // to absorb); list every one so a silently missing result cannot hide.
  for (const [id, v] of Object.entries(written)) {
    const m = v.match(/[^<>]{0,50}(>–<|[ (>]–[ )%<])[^<>]{0,20}/g);
    if (m) console.log(`note: placeholder in #${id}: ${m.slice(0, 2).join(" | ")}`);
  }
  if (errors.length) { console.error("UI SMOKE FAILED\n" + errors.join("\n")); process.exit(1); }
  console.log(`UI smoke OK: ${Object.keys(written).length} elements rendered, ` +
              `${idx.weeks.length} weeks x ${Math.min(60, idx.states.length)} states explored`);
})();
