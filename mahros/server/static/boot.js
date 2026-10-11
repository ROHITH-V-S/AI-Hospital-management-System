"use strict";
// ---------------------------------------------------------------- boot
const R = {
  emergency: renderEmergency, live: renderLive, overview: renderOverview,
  trust: renderTrust, forecast: renderForecast, coord: renderCoord, audit: renderAudit,
  limits: async () => {},
  warning: typeof renderWarning === "function" ? renderWarning : async () => {},
  resources: typeof renderResources === "function" ? renderResources : async () => {},
  datatrust: typeof renderDataTrust === "function" ? renderDataTrust : async () => {},
  ev_emergency: typeof renderEvEmergency === "function" ? renderEvEmergency : async () => {},
  ev_warning: typeof renderEvWarning === "function" ? renderEvWarning : async () => {},
  ev_staff: typeof renderEvStaff === "function" ? renderEvStaff : async () => {},
};
const ALWAYS = new Set(["audit"]);           // re-read every time it is opened
const done = new Set();
async function render(tab){
  if (done.has(tab) && !ALWAYS.has(tab)) return;
  try { await R[tab](); done.add(tab); }
  catch (e) {
    const el = document.getElementById(tab);
    el.insertAdjacentHTML("afterbegin", `<div class="not"><b>Could not load this screen</b>${esc(e.message)}</div>`);
  }
}
(function start(){
  const q = new URLSearchParams(location.search);
  let tab = q.get("tab");
  if (!tab){ try { tab = localStorage.getItem("mahros-tab"); } catch (e) {} }
  if (!tab || !document.getElementById(tab) || !document.querySelector(`#mainnav button[data-tab="${tab}"]`)) tab = "emergency";
  if (q.get("sub")) EV.sub = q.get("sub");
  showTab(tab);
  if (tab === "evidence") showSub(EV.sub);
})();
