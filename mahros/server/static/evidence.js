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

// ---------------------------------------------------------------- EVIDENCE 5: surge early warning (real data)
async function renderEvWarning(){
  const w = await get("surge_warning.json");
  const M = w.methods, mo = M.model, nt = M.near_threshold, cmp = w.comparisons.model_vs_near_threshold;
  const name = {near_threshold: "Simple rule: area already close to 85%", trend: "Simple rule: occupancy trend projected 2 weeks",
                neighbours: "Simple rule: many neighbouring hospitals rising together", model: "MAHROS model (all signals)",
                model_without_ed: "MAHROS model without ED visits", model_without_admissions: "MAHROS model without COVID/flu admissions"};
  const better = cmp.ci95[0] > 0;
  $("#ew-answer").textContent = `Partly. On 2023–24 weeks the model never saw, it caught ${pct(mo.test_onset.recall, 0)} of areas that went from below 85% to above it within 2 weeks, and ${pct(mo.test_onset.precision, 0)} of its warnings came true. ` +
    (better ? `That is ${(100 * cmp.diff).toFixed(0)} F1 points better than the best simple rule (95% range ${(100 * cmp.ci95[0]).toFixed(0)}–${(100 * cmp.ci95[1]).toFixed(0)}), ` : `That is not clearly better than the best simple rule, `) +
    `but only ${pct(mo.lead.warned_1_week_or_more, 0)} of surges were warned at least a week ahead.`;
  const row = k => { const r = M[k], o = r.test_onset, L = r.lead;
    return `<tr${k === "model" ? ' style="font-weight:650"' : ""}><td>${esc(name[k])}</td><td class="n">${pct(o.precision, 0)}</td><td class="n">${pct(o.recall, 0)}</td><td class="n">${o.f1.toFixed(2)}</td><td class="n">${num(o.alerts)}</td><td class="n">${pct(L.warned_1_week_or_more, 0)}</td><td class="n">${pct(L.warned_2_weeks, 0)}</td></tr>`; };
  const months = w.monthly;
  const chart = lineChart([
    {points: months.map(r => [new Date(r.month + "-01"), r.areas_above_85]), color: css("--red")},
    {points: months.map(r => [new Date(r.month + "-01"), r.alerts_share]), color: css("--chart1")}],
    {h: 220, ymin: 0, yfmt: v => (100 * v).toFixed(0) + "%"});
  const sw = w.threshold_sweep;
  const PLAIN = {area_occ: "How full the area is now", area_occ_d2: "Change over the last 2 weeks", area_occ_d1: "Change over the last week",
                 woy_sin: "Time of year", woy_cos: "Time of year (2)", log_area_beds: "Size of the area (beds)", n_neighbours: "Number of hospitals in the area",
                 area_icu_occ: "How full the area's ICUs are", area_icu_d1: "ICU change over the last week", covid_adm_growth: "Growth in COVID-19 admissions",
                 flu_adm_growth: "Growth in flu admissions", ed_growth: "Growth in ED visits", covid_adm_per_100beds: "COVID-19 admissions per 100 beds",
                 flu_adm_per_100beds: "Flu admissions per 100 beds", rising_share: "Share of hospitals rising", rising_neighbours: "Hospitals rising"};
  const imp = Object.entries(w.importance || {}).filter(([k]) => k !== "error").slice(0, 6).map(([k, v]) => [PLAIN[k] || k, v]);
  $("#ew-body").innerHTML = `
    <div class="banner real"><b>Real data, no simulation.</b> ${num(w.rows.neighbourhoods)} areas (a hospital and every hospital within ${w.definition.radius_km} km), weekly. Trained ${w.split.train[0]}–${w.split.train[1]}, alarm level set on ${w.split.calib[0]}–${w.split.calib[1]}, tested ${w.split.test[0]}–${w.split.test[1]}.</div>
    <h2>Areas below 85% now: who reached 85% within 2 weeks? (test period)</h2>
    <div class="card"><table><tr><th>Method</th><th class="n">Warnings that came true</th><th class="n">Surges caught</th><th class="n">F1</th><th class="n">Warnings issued</th><th class="n">Surges warned ≥1 week ahead</th><th class="n">2 weeks ahead</th></tr>
      ${["model", "near_threshold", "trend", "neighbours", "model_without_ed", "model_without_admissions"].map(row).join("")}</table>
      <p class="small muted" style="margin:8px 0 0">${num(w.rows.test_onset)} area-weeks below 85% in the test period; ${pct(w.onset_base_rate_test, 1)} of them reached 85% within 2 weeks. "Surges" = ${num(mo.lead.events)} moments when an area crossed 85% after 4 weeks below. Every alarm level was chosen on the calibration weeks, never on the test weeks.</p></div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>Is the model better than the simple rules?</h3><table><tr><th>Model minus…</th><th class="n">F1 difference</th><th class="n">95% range</th></tr>
        ${Object.entries(w.comparisons).map(([k, v]) => `<tr><td>${esc(name[k.replace("model_vs_", "")])}</td><td class="n">${(100 * v.diff).toFixed(1)} pts</td><td class="n small muted">${(100 * v.ci95[0]).toFixed(1)} to ${(100 * v.ci95[1]).toFixed(1)}</td></tr>`).join("")}</table>
        <p class="small muted" style="margin:6px 0 0">Ranges from resampling whole states (areas inside a state overlap).</p></div>
      <div class="card"><h3>Does it depend on the 85% line?</h3><table><tr><th>Line</th><th class="n">Model F1</th><th class="n">Simple rule F1</th><th class="n">Share that crossed</th></tr>
        ${Object.entries(sw).map(([k, v]) => `<tr><td>${pct(+k, 0)}</td><td class="n">${v.model.f1.toFixed(2)}</td><td class="n">${v.near_threshold.f1.toFixed(2)}</td><td class="n">${pct(v.onset_base_rate, 1)}</td></tr>`).join("")}
        <tr><td><b>85% (used)</b></td><td class="n"><b>${mo.test_onset.f1.toFixed(2)}</b></td><td class="n">${nt.test_onset.f1.toFixed(2)}</td><td class="n">${pct(w.onset_base_rate_test, 1)}</td></tr></table></div>
    </div>
    <h2>Month by month in the test period</h2>
    <div class="card">${chart}<div class="legend"><span><i style="background:var(--red)"></i>Areas over 85% full</span><span><i style="background:var(--chart1)"></i>Areas flagged by the model (including those already over 85%)</span></div></div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>What the model leans on</h3><p class="small muted" style="margin:0 0 6px">Drop in ranking quality when one signal is shuffled (bigger = more important).</p><table>${imp.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v.toFixed(3)}</td></tr>`).join("")}</table>
        <p class="small muted" style="margin:6px 0 0">Mostly the area's own occupancy and its recent change. ED visits were present for ${pct(w.ed_available_share_test, 0)} of test area-weeks (at least one hospital in the area still reported them); removing them did not change the result.</p></div>
      <div class="card"><h3>Biggest surges it missed (by area size)</h3>${w.largest_misses.map(m => `<div class="prop">${esc(nicePk(m.centre))}, ${esc(nicePk(m.city))}, ${esc(m.state)} — week of ${esc(m.week)}</div>`).join("")}</div>
    </div>
    <div class="not"><b>What this does not show</b><ul>
      <li>It is a warning about hospital capacity from hospital reports. It cannot see an outbreak in the community before patients arrive; symptom data is not public.</li>
      <li>Most of its skill comes from occupancy that is already high and rising. Sudden jumps with no build-up are missed.</li>
      <li>Areas overlap, so the scores are not independent; ranges come from resampling whole states.</li>
      <li>It was trained on the COVID-19 years. How it would do in a new kind of wave is unknown.</li></ul></div>`;
}

// ---------------------------------------------------------------- EVIDENCE 6: staffing direction check
async function renderEvStaff(){
  const s = await get("staffing_check.json");
  const A = s.periods["2020-08..2022-12"], B = s.periods["2023-01..2024-04"];
  $("#es-answer").textContent = `Only weakly, and only while hospitals were answering. In 2020–22, when ${pct(A.median_answered_share, 0)} of hospitals answered the staffing question, our estimate and the real reports moved in the same direction in ${A.states_positive} of ${A.states_tested} states, but weakly (median correlation over time ${A.within_state_spearman_median.toFixed(2)}). In 2023–24, when ${pct(B.median_answered_share, 0)} answered, there was no relationship (${B.within_state_spearman_median.toFixed(2)}). And the levels differ: ${pct(A.mean_real_share, 0)} of hospitals really reported a shortage in an average week, our estimate flagged ${pct(A.mean_est_share, 1)}.`;
  const nat = s.national_weekly;
  const chart = lineChart([
    {points: nat.map(r => [new Date(r.week), r.real_share]), color: css("--red")},
    {points: nat.map(r => [new Date(r.week), r.est_share]), color: css("--chart1")}],
    {h: 230, ymin: 0, yfmt: v => (100 * v).toFixed(0) + "%"});
  const row = (n, P) => `<tr><td>${esc(n)}</td><td class="n">${pct(P.median_answered_share, 0)}</td><td class="n">${num(P.state_weeks)}</td><td class="n">${P.within_state_spearman_median.toFixed(2)}</td><td class="n small muted">${P.within_state_spearman_iqr.map(x => x.toFixed(2)).join(" to ")}</td><td class="n">${P.states_positive} of ${P.states_tested}</td><td class="n">${P.pooled_spearman.toFixed(2)}</td><td class="n">${pct(P.mean_real_share, 1)}</td><td class="n">${pct(P.mean_est_share, 1)}</td></tr>`;
  const lags = Object.entries(A.lag_median_spearman).sort((a, b) => +a[0] - +b[0]);
  $("#es-body").innerHTML = `
    <div class="banner sim"><b>Estimate vs real.</b> No public data reports staff per hospital, so MAHROS estimates each hospital's nurses from its usual staffed beds (ICU 1:2, ward 1:5) and flags a hospital as short when this week's patients need more. The only real staffing signal is state-level: how many hospitals said "critical staffing shortage today" (HHS g62h-syeh). This checks whether the two point the same way — not whether any one hospital's number is right.</div>
    <h2>Share of hospitals short of staff, national weekly average</h2>
    <div class="card">${chart}<div class="legend"><span><i style="background:var(--red)"></i>Real: share of answering hospitals reporting a critical shortage</span><span><i style="background:var(--chart1)"></i>Estimated: share of hospitals our estimate flags as short</span></div></div>
    <h2>Do they move together, state by state?</h2>
    <div class="card"><table><tr><th>Period</th><th class="n">Hospitals answering</th><th class="n">State-weeks</th><th class="n">Correlation over time (median state)</th><th class="n">Middle half of states</th><th class="n">States positive</th><th class="n">Pooled</th><th class="n">Real share</th><th class="n">Estimated share</th></tr>
      ${row("2020-08 to 2022-12", A)}${row("2023-01 to 2024-04", B)}</table>
      <p class="small muted" style="margin:8px 0 0">Spearman rank correlation. Lead or lag (2020–22, median state): ${lags.map(([k, v]) => `${k > 0 ? "+" : ""}${k} wk ${v.toFixed(2)}`).join(" · ")} — flat, so neither series clearly leads.</p></div>
    <div class="not"><b>What this does not show</b><ul>
      <li>It says nothing about any single hospital's staff numbers; those remain estimates.</li>
      <li>Real shortages also come from absences and vacancies, which bed counts cannot see — a likely reason the estimate flags far fewer hospitals than really reported shortages.</li>
      <li>From 2023 most hospitals stopped answering the staffing question, so the real series became too thin to check against.</li>
      <li>Use the staff-loan plan as a way to organise lending, not as a measurement of who is short.</li></ul></div>`;
}
