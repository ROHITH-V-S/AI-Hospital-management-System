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
const js = html.split("<script>")[1].split("</script>")[0];
const UI = path.join(ROOT, "results/ui");

const written = {};
function el(id) {
  const o = {
    id, _html: "", _text: "", value: "0", options: [], dataset: {}, classList: { toggle() {} },
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
global.fetch = async (url, opt) => {
  if (url.startsWith("/ui/")) {
    const p = path.join(UI, url.slice(4));
    if (!fs.existsSync(p)) return { ok: false, status: 404 };
    const data = JSON.parse(fs.readFileSync(p, "utf8"));
    return { ok: true, json: async () => data };
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
  const run = new Function(js + "\nreturn {renderOverview, renderTrust, renderForecast, renderCoord, drawWeek, renderAudit};");
  const R = run();
  const errors = [];
  for (const [name, f] of Object.entries(R)) {
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
