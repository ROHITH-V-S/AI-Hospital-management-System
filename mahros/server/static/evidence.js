"use strict";
// ---------------------------------------------------------------- EVIDENCE 4: emergency transfers (simulation)
const POL_NAME = {mahros: "MAHROS: ask every capable hospital at once",
                  phone_nearest: "Phone, nearest hospital first",
                  phone_informed: "Phone, hospitals whose report shows ICU room first"};
const fmtMin = x => x == null || isNaN(x) ? "–" : `${x.toFixed(1)} min`;
const ci = c => `${c[0] >= 0 ? "+" : ""}${c[0].toFixed(1)} to ${c[1] >= 0 ? "+" : ""}${c[1].toFixed(1)}`;

async function renderEvEmergency(){
  const e = await get("emergency_eval.json");
  const S = e.summary, m = S.mahros, pn = S.phone_nearest, pi = S.phone_informed;
  const cN = e.comparisons.mahros_vs_phone_nearest, cI = e.comparisons.mahros_vs_phone_informed;
  const busy = e.by_group.busy_weeks, other = e.by_group.other_weeks;
  const weeks = Object.values(e.states).reduce((a, s) => a + s.weeks.length, 0);
  const faster = cN.ttb_mean.ci95[1] < 0, slower = cN.ttb_mean.ci95[0] > 0;
  const tailGain = pn.ttb_p90 - m.ttb_p90;
  const lead = faster ? (tailGain > (pn.ttb_mean - m.ttb_mean) ? "On average, yes — and most for the patients who wait longest."
                                                              : "On average, yes.")
             : slower ? "No — on average phoning was faster." : "Not clearly: the difference is within the noise.";
  $("#ee-answer").textContent =
    `${lead} Across ${weeks} real weeks in Arizona and Massachusetts (${e.seeds} simulated runs each), ` +
    `MAHROS confirmed a bed in ${m.ttb_mean.toFixed(1)} minutes on average, against ${pn.ttb_mean.toFixed(1)} phoning the nearest hospital first ` +
    `and ${pi.ttb_mean.toFixed(1)} phoning first the hospitals whose report shows room. For the slowest 1 in 10 patients: ` +
    `${m.ttb_p90.toFixed(0)} vs ${pn.ttb_p90.toFixed(0)} minutes. When the nearest hospital has room, one phone call is as fast or faster.`;
  const rows = ["mahros", "phone_nearest", "phone_informed"].map(k => {
    const s = S[k];
    return `<tr><td>${esc(POL_NAME[k])}</td><td class="n"><b>${fmtMin(s.ttb_mean)}</b></td><td class="n">${fmtMin(s.ttb_p50)}</td><td class="n">${fmtMin(s.ttb_p90)}</td><td class="n">${pct(s.within_window, 1)}</td><td class="n">${pct(s.placed, 1)}</td><td class="n">${s.calls_mean.toFixed(2)}</td><td class="n">${s.coord_min_mean.toFixed(1)}</td></tr>`;
  }).join("");
  const diff = (c, k, unit, better) => `<td class="n">${c[k].mean_diff >= 0 ? "+" : ""}${unit === "%" ? (100 * c[k].mean_diff).toFixed(1) + " pts" : c[k].mean_diff.toFixed(1) + " min"}</td><td class="n small muted">${unit === "%" ? ci(c[k].ci95.map(x => 100 * x)) + " pts" : ci(c[k].ci95) + " min"}</td>`;
  const sens = Object.entries(e.sensitivity).map(([k, v]) => `<tr><td>${esc(k.replace("_", " "))}</td><td class="n">${fmtMin(v.mahros_ttb_mean)}</td><td class="n">${fmtMin(v.phone_ttb_mean)}</td><td class="n">${v.ttb_mean.toFixed(1)}</td><td class="n">${v.ttb_p90.toFixed(1)}</td><td class="n">${(100 * v.within_window).toFixed(1)}</td></tr>`).join("");
  const ranges = Object.values(e.sensitivity).map(v => v.ttb_mean);
  const cal = e.calibration;
  const reg = e.param_registry.map(p => `<tr><td><b>${esc(p.name)}</b></td><td class="n">${p.value}</td><td>${p.status === "cited" ? provTag("observed").replace(">observed<", ">cited<") : provTag("estimated").replace(">estimated<", ">assumption<")}</td><td class="small">${esc(p.source)}</td><td class="small muted">${p.sweep.join(", ")}</td></tr>`).join("");
  $("#ee-body").innerHTML = `
    <div class="banner sim"><b>Simulation grounded in real data</b> — real hospitals (${e.states.AZ.hospitals} in Arizona, ${e.states.MA.hospitals} in Massachusetts), real CMS capability, real OSRM road times, each hospital's real weekly ICU report and ED visits, the real state staffing series. Simulated: minute-by-minute beds and the transfer requests. These are not measurements of real transfers.</div>
    <h2>Time to a confirmed bed, all ${weeks} weeks</h2>
    <div class="card"><table><tr><th>Method</th><th class="n">Mean</th><th class="n">Median</th><th class="n">Slowest 10%</th><th class="n">Reached care inside the clinical window</th><th class="n">Bed found</th><th class="n">Phone calls per patient</th><th class="n">Staff minutes on the phone</th></tr>${rows}</table>
      <p class="small muted" style="margin:8px 0 0">Time to bed = request → a hospital confirms. Both methods end with one doctor-to-doctor call (${e.params.call_min} min); MAHROS first waits ${e.params.bid_window_min} min for answers. "Bed found" below 100%: no capable hospital in reach had room at that moment.</p></div>
    <h2>Paired differences (MAHROS minus phone; negative = MAHROS faster)</h2>
    <div class="card"><table><tr><th>Compared with</th><th class="n">Mean time to bed</th><th class="n">95% range</th><th class="n">Slowest 10%</th><th class="n">95% range</th><th class="n">Inside the window</th><th class="n">95% range</th></tr>
      <tr><td>Phone, nearest first</td>${diff(cN, "ttb_mean")}${diff(cN, "ttb_p90")}${diff(cN, "within_window", "%")}</tr>
      <tr><td>Phone, report-informed order</td>${diff(cI, "ttb_mean")}${diff(cI, "ttb_p90")}${diff(cI, "within_window", "%")}</tr></table>
      <p class="small muted" style="margin:8px 0 0">${cN.ttb_mean.units} paired units (state × week × run); the same simulated patients face both methods. 95% ranges from 2,000 bootstrap resamples.</p></div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>Busiest weeks vs other weeks</h3><table><tr><th></th><th class="n">MAHROS</th><th class="n">Phone, nearest</th><th class="n">Phone calls</th></tr>
        <tr><td>4 busiest weeks per state (mean)</td><td class="n">${fmtMin(busy.summary.mahros.ttb_mean)}</td><td class="n">${fmtMin(busy.summary.phone_nearest.ttb_mean)}</td><td class="n">${busy.summary.phone_nearest.calls_mean.toFixed(2)}</td></tr>
        <tr><td>4 other weeks per state (mean)</td><td class="n">${fmtMin(other.summary.mahros.ttb_mean)}</td><td class="n">${fmtMin(other.summary.phone_nearest.ttb_mean)}</td><td class="n">${other.summary.phone_nearest.calls_mean.toFixed(2)}</td></tr>
        <tr><td>Busiest weeks, slowest 10%</td><td class="n">${fmtMin(busy.summary.mahros.ttb_p90)}</td><td class="n">${fmtMin(busy.summary.phone_nearest.ttb_p90)}</td><td></td></tr></table></div>
      <div class="card"><h3>Does the simulation start from reality?</h3><p class="small" style="margin:0">With no transfers, each simulated ICU averaged <b>${pct(cal.total_simulated_over_reported, 1)}</b> of its reported census in total (median hospital ${pct(cal.median_ratio, 1)}, middle half ${pct(cal.iqr_ratio[0], 0)}–${pct(cal.iqr_ratio[1], 0)}), over ${num(cal.hospital_weeks)} hospital-weeks.</p>
        <p class="small muted" style="margin:6px 0 0">${esc(cal.note)} It shows the starting point is the real report; it does not show that minute-level behaviour is real — no public minute-level data exists.</p></div>
    </div>
    <h2>Does the answer depend on our assumptions?</h2>
    <div class="card"><table><tr><th>Change one assumption</th><th class="n">MAHROS mean</th><th class="n">Phone mean</th><th class="n">Difference, mean (min)</th><th class="n">Difference, slowest 10% (min)</th><th class="n">Inside window (pts)</th></tr>${sens}</table>
      <p class="small muted" style="margin:8px 0 0">Across every one-at-a-time change, the mean difference ranges from ${Math.min(...ranges).toFixed(1)} to ${Math.max(...ranges).toFixed(1)} minutes (negative = MAHROS faster). Report it as this range, not as one number. Rows identical to the base case are not an error: cath-lab and ventilator settings change the time to definitive care, not the time to a confirmed bed, and the staffing cut has no effect because almost no hospital reported a staffing shortage in 2023–24 (the forced 20% row shows what a short-staffed week does).</p></div>
    <h2>Every number the simulation uses</h2>
    <div class="card"><table><tr><th>Parameter</th><th class="n">Value</th><th>Status</th><th>Source / reason</th><th>Swept</th></tr>${reg}</table></div>
    <div class="not"><b>What this does not show</b><ul>
      <li>No real patient was transferred. There is no public record of real transfers to compare with.</li>
      <li>The gain depends mostly on how long a phone call takes and how often the nearest hospital is full. With 5-minute calls and quiet weeks, phoning is often as fast.</li>
      <li>Clinical windows are generous (120–240 min) compared with the minutes saved, so the share of patients reaching care in time changes little. The value is in the slow tail and in staff time, not in a dramatic survival claim.</li>
      <li>Ambulance availability, traffic and the time to stabilise a patient before transport are not modelled; they are the same for both methods.</li>
      <li>Hospitals answer honestly from their simulated state. The model does not study hospitals hiding beds.</li></ul></div>`;
}
