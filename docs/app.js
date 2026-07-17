const COMPONENTS = ["All", "6Y", "12Y", "LDG", "E1", "E2"];
const VIEWS = ["overview", "assumptions", "utilization", "events", "inflows", "cashflow", "risk", "analysis", "audit"];
const STORAGE_KEY = "aircraft-reserve-model-draft-v2";

const demoData = structuredClone(window.DASHBOARD_DATA);
let currentData = structuredClone(demoData);
let draftCase = applyV1DerivedBaseDates(loadDraft() || structuredClone(demoData.case));
let currentView = location.hash.slice(1) || "overview";
if (currentView === "case-questions") currentView = "analysis";
let selectedComponent = "All";
let isDirty = JSON.stringify(draftCase) !== JSON.stringify(currentData.case);
let caseReport = null;
let caseReportRunning = false;
let caseReportError = "";
let analysisMode = "report";
let analysisReportType = "full_analysis";
let analysisQuestion = "";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(value, compact = false) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 2 : 0,
  }).format(Number(value));
}

function number(value, digits = 0) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Number(value));
}

function month(value) {
  return new Intl.DateTimeFormat("en-US", { month: "short", year: "2-digit", timeZone: "UTC" })
    .format(new Date(`${value}T00:00:00Z`));
}

function longDate(value) {
  if (!value) return "—";
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(parsed);
}

function dateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short",
  }).format(parsed);
}

function percent(value, digits = 1) {
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function percentInput(value) {
  return String(Number((Number(value) * 100).toFixed(8)));
}

function loadDraft() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

function saveDraft() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(draftCase));
  isDirty = JSON.stringify(draftCase) !== JSON.stringify(currentData.case);
  updateStateIndicators();
}

function showToast(message, tone = "success") {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.className = `toast visible ${tone}`;
  window.setTimeout(() => { toast.className = "toast"; }, 3200);
}

function updateStateIndicators() {
  const state = document.querySelector("#calculation-state");
  const modelState = document.querySelector("#model-state");
  const runButton = document.querySelector("#run-model");
  if (isDirty) {
    state.className = "pending-state";
    state.innerHTML = "<i></i> Inputs changed";
    modelState.textContent = "Draft not calculated";
    runButton.textContent = "Run updated model";
  } else {
    state.className = "";
    state.innerHTML = "<i></i> Validated";
    modelState.textContent = "Model validated";
    runButton.textContent = "Run model";
  }
}

function updateCaseHeader() {
  document.querySelector("#case-title").textContent = `${draftCase.aircraft_type} · ${draftCase.lessee}`;
  document.querySelector("#case-context").textContent = currentData.run.demo_case ? "Single-lease calculation reference" : "User-defined single-lease scenario";
  document.querySelector("#lease-start").textContent = longDate(draftCase.lease_start_date);
  document.querySelector("#analysis-date").textContent = longDate(draftCase.analysis_date);
  document.querySelector("#lease-expiry").textContent = longDate(draftCase.lease_expiry_date);
  document.querySelector("#forecast-months").textContent = `${currentData.summary.forecast_months} months`;
  document.querySelector("#model-version").textContent = `V1.1 · Reference · ${currentData.run.model_version}`;
  updateStateIndicators();
}

function heading(eyebrow, title, note, actions = "") {
  return `<section class="overview-heading page-heading"><div><p class="eyebrow">${escapeHtml(eyebrow)}</p><h2>${escapeHtml(title)}</h2></div><div class="heading-side">${note ? `<p class="overview-note">${escapeHtml(note)}</p>` : ""}${actions}</div></section>`;
}

function metric(label, value, note, className = "") {
  return `<article class="${className}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`;
}

function componentFilters() {
  return `<div class="component-filter" aria-label="Filter by component">${COMPONENTS.map((component) => `<button data-component="${component}" class="${selectedComponent === component ? "selected" : ""}">${component}</button>`).join("")}</div>`;
}

function reserveAccountSelector(context = "settlement") {
  const accounts = [{ code: "All", name: "Portfolio summary" }, ...draftCase.components.map((component) => ({ code: component.code, name: component.name }))];
  const active = accounts.find((account) => account.code === selectedComponent) || accounts[0];
  const riskContext = context === "risk";
  const title = riskContext ? "Select the account to assess" : "Select the account to trace";
  const description = riskContext
    ? "Assess whether each forecast maintenance event is fully covered by its matching component reserve, and isolate funding gaps requiring attention."
    : "Each maintenance event is settled only against its matching component reserve. Choose an account to follow its opening balance, collections, event outflow and remaining balance.";
  return `<section class="reserve-account-control"><div class="reserve-account-intro"><div><p class="eyebrow">Reserve account view</p><h3>${title}</h3><p>${description}</p></div><div class="active-account"><span>Currently viewing</span><strong>${active.code === "All" ? "All component accounts" : escapeHtml(active.code)}</strong><small>${escapeHtml(active.name)}</small></div></div><div class="reserve-account-tabs" role="group" aria-label="Select reserve account">${accounts.map((account) => `<button type="button" data-component="${account.code}" class="${selectedComponent === account.code ? "selected" : ""}" aria-pressed="${selectedComponent === account.code}"><strong>${account.code === "All" ? "All accounts" : escapeHtml(account.code)}</strong><small>${escapeHtml(account.name)}</small></button>`).join("")}</div></section>`;
}

function cashflowChart(cashflows) {
  const maxFlow = Math.max(...cashflows.flatMap((row) => [Number(row.total_reserve_inflow), Number(row.total_reserve_outflow)]));
  const maxBalance = Math.max(...cashflows.map((row) => Number(row.total_closing_balance)));
  return `<div class="chart-frame"><div class="axis-label axis-top">Peak</div><div class="axis-label axis-middle">$0</div><div class="cashflow-chart" role="img" aria-label="Monthly reserve cash flow"><div class="chart-midline"></div>${cashflows.map((row, index) => {
    const inflow = Math.max(1.5, (Number(row.total_reserve_inflow) / maxFlow) * 42);
    const outflow = Math.max(0, (Number(row.total_reserve_outflow) / maxFlow) * 42);
    const balance = 18 + (Number(row.total_closing_balance) / maxBalance) * 64;
    return `<div class="chart-month ${row.mx_calendar === "-" ? "" : "event-month"}" style="--inflow-height:${inflow}%;--outflow-height:${outflow}%;--balance-position:${balance}%" title="${month(row.date)} · Inflow ${money(row.total_reserve_inflow)} · Reimbursement ${money(row.total_reserve_outflow)} · Balance ${money(row.total_closing_balance)}"><span class="balance-point"></span><span class="inflow-bar"></span><span class="outflow-bar"></span>${row.mx_calendar === "-" ? "" : `<span class="event-label">${escapeHtml(row.mx_calendar)}</span>`}${index % 6 === 0 || index === cashflows.length - 1 ? `<time>${month(row.date)}</time>` : ""}</div>`;
  }).join("")}</div></div>`;
}

function fundingTable(events) {
  if (!events.length) return `<div class="empty-state">No forecast events for this component.</div>`;
  return `<div class="table-scroll"><table><thead><tr><th>Component account</th><th>Event date</th><th class="number">Escalated cost</th><th class="number">Component reserve available</th><th class="number">Coverage</th><th class="number">Shortfall</th><th class="number">Post-event reserve</th><th>Status</th></tr></thead><tbody>${events.map((event) => {
    const coverage = Math.min(100, Number(event.coverage_ratio) * 100);
    return `<tr><td><strong class="component-code">${escapeHtml(event.component)}</strong><span class="component-name">${escapeHtml(event.component_name)}</span></td><td>${month(event.event_date)}</td><td class="number">${money(event.event_cost)}</td><td class="number">${money(event.available_reserve)}</td><td class="number coverage-cell"><span>${percent(event.coverage_ratio)}</span><i><b class="${event.fully_funded ? "funded" : "underfunded"}" style="width:${coverage}%"></b></i></td><td class="number ${event.fully_funded ? "" : "shortfall"}">${event.fully_funded ? "—" : money(event.shortfall)}</td><td class="number">${money(event.closing_balance_after_event)}</td><td><span class="status ${event.fully_funded ? "funded" : "underfunded"}">${event.fully_funded ? "Fully funded" : "Shortfall"}</span></td></tr>`;
  }).join("")}</tbody></table></div>`;
}

function renderOverview() {
  const data = currentData;
  return `${heading("Portfolio overview", "Maintenance reserve position", "Forecast values include opening balances accumulated from the full historical simulation.")}
    <section class="metric-grid">${metric("Forecast reserve inflow", money(data.summary.forecast_reserve_inflow, true), `${data.summary.forecast_months}-month collection`)}${metric("Forecast reimbursement", money(data.summary.forecast_reimbursement, true), `Across ${data.summary.component_event_count} component events`)}${metric("Total forecast shortfall", money(data.summary.forecast_shortfall, true), `${data.summary.underfunded_event_count} underfunded events`, "risk-metric")}${metric("Lease-end reserve balance", money(data.summary.lease_end_reserve_balance, true), `Closing position · ${month(draftCase.lease_expiry_date)}`)}</section>
    <section class="panel assumption-snapshot"><div class="panel-header"><div><p class="eyebrow">Reference inputs</p><h3>Model assumptions</h3></div><button class="button secondary compact" data-open-view="assumptions">Edit assumptions</button></div><div class="snapshot-grid"><div><span>Aircraft / lessee</span><strong>${escapeHtml(draftCase.aircraft_type)}</strong><small>${escapeHtml(draftCase.lessee)}</small></div><div><span>Lease period</span><strong>${longDate(draftCase.lease_start_date)}</strong><small>to ${longDate(draftCase.lease_expiry_date)}</small></div><div><span>Analysis date</span><strong>${longDate(draftCase.analysis_date)}</strong><small>${data.summary.forecast_months} forecast months</small></div><div><span>Default utilization</span><strong>${number(draftCase.default_monthly_fh)} FH / month</strong><small>${number(draftCase.default_monthly_fc)} FC / month</small></div></div><div class="table-scroll"><table><thead><tr><th>Component</th><th>Event driver</th><th class="number">Interval</th><th class="number">Base event cost</th><th class="number">Cost escalation</th><th>Reserve basis</th><th class="number">Base reserve rate</th><th class="number">Reserve escalation</th></tr></thead><tbody>${draftCase.components.map((component) => `<tr><td><strong class="component-code">${escapeHtml(component.code)}</strong><span class="component-name">${escapeHtml(component.name)}</span></td><td>${escapeHtml(component.event_driver.replaceAll("_", " "))}</td><td class="number">${number(component.interval)}</td><td class="number">${money(component.base_cost)}</td><td class="number">${percent(component.annual_cost_escalation)}</td><td>${escapeHtml(component.reserve_basis.replaceAll("_", " "))}</td><td class="number">${money(component.base_reserve_rate)}</td><td class="number">${percent(component.annual_reserve_escalation)}</td></tr>`).join("")}</tbody></table></div><div class="assumption-footnote"><strong>Public demonstration basis.</strong> The private reference timeline is shifted forward by 32 months. Aircraft age and relative event timing are preserved, while January-based escalation is recalculated from the displayed dates.</div></section>
    <section class="panel cashflow-panel"><div class="panel-header"><div><p class="eyebrow">Monthly cash flow</p><h3>Collections, reimbursements and closing balance</h3></div><div class="chart-legend"><span><i class="legend-inflow"></i> Inflow</span><span><i class="legend-outflow"></i> Reimbursement</span><span><i class="legend-balance"></i> Closing balance</span></div></div>${cashflowChart(data.cashflows)}</section>
    <section class="panel funding-panel"><div class="panel-header funding-header"><div><p class="eyebrow">Event funding</p><h3>Forecast maintenance exposure</h3></div>${componentFilters()}</div>${fundingTable(filteredEvents())}</section>
    ${auditStrip()}`;
}

function inputField(label, field, value, type = "text", extra = "") {
  return `<label class="field"><span>${escapeHtml(label)}</span><input type="${type}" data-case-field="${field}" value="${escapeHtml(value)}" ${extra}></label>`;
}

function componentInput(index, field, value, type = "number", step = "any", transform = "", extra = "") {
  return `<input type="${type}" data-component-index="${index}" data-component-field="${field}" data-transform="${transform}" value="${escapeHtml(value ?? "")}" step="${step}" ${extra}>`;
}

function renderAssumptions() {
  const caseInputs = draftCase;
  return `${heading("Model inputs", "Inputs and assumptions", "Every value below is part of the deterministic Stage 1–4 request. Changes are saved locally until the model is run.", `<span class="draft-badge ${isDirty ? "visible" : ""}">Unsaved calculation changes</span>`)}
    <form id="assumptions-form" autocomplete="off">
      <section class="panel form-panel"><div class="panel-header"><div><p class="eyebrow">Aircraft and lease</p><h3>Aircraft and lease timeline</h3></div></div><div class="form-grid">${inputField("Aircraft type", "aircraft_type", caseInputs.aircraft_type)}${inputField("Lessee", "lessee", caseInputs.lessee)}${inputField("Date of manufacture", "date_of_manufacture", caseInputs.date_of_manufacture, "date")}${inputField("Lease start", "lease_start_date", caseInputs.lease_start_date, "date")}${inputField("Analysis date", "analysis_date", caseInputs.analysis_date, "date")}${inputField("Lease expiry", "lease_expiry_date", caseInputs.lease_expiry_date, "date")}${inputField("Default monthly flight hours", "default_monthly_fh", caseInputs.default_monthly_fh, "number", 'min="0" step="any"')}${inputField("Default monthly flight cycles", "default_monthly_fc", caseInputs.default_monthly_fc, "number", 'min="0" step="any"')}</div></section>
      <section class="panel form-panel"><div class="panel-header"><div><p class="eyebrow">Maintenance assumptions</p><h3>Intervals, event costs and reserve rates</h3></div><span class="panel-note">Escalation inputs shown as annual percentages</span></div><div class="table-scroll assumption-table"><table><thead><tr><th>Component</th><th>Driver</th><th class="number">Interval</th><th class="number">Base cost</th><th class="number">Cost escalation</th><th>Reserve basis</th><th class="number">Base reserve rate</th><th class="number">Reserve escalation</th><th class="number">Usage at lease start</th></tr></thead><tbody>${caseInputs.components.map((component, index) => `<tr><td><strong class="component-code">${escapeHtml(component.code)}</strong>${componentInput(index, "name", component.name, "text")}</td><td><select data-component-index="${index}" data-component-field="event_driver"><option value="calendar_months" ${component.event_driver === "calendar_months" ? "selected" : ""}>Calendar months</option><option value="flight_hours" ${component.event_driver === "flight_hours" ? "selected" : ""}>Flight hours</option><option value="flight_cycles" ${component.event_driver === "flight_cycles" ? "selected" : ""}>Flight cycles</option></select></td><td>${componentInput(index, "interval", component.interval)}</td><td>${componentInput(index, "base_cost", component.base_cost)}</td><td>${componentInput(index, "annual_cost_escalation", percentInput(component.annual_cost_escalation), "number", "0.01", "percent")}</td><td><select data-component-index="${index}" data-component-field="reserve_basis"><option value="per_month" ${component.reserve_basis === "per_month" ? "selected" : ""}>Per month</option><option value="per_flight_hour" ${component.reserve_basis === "per_flight_hour" ? "selected" : ""}>Per flight hour</option><option value="per_flight_cycle" ${component.reserve_basis === "per_flight_cycle" ? "selected" : ""}>Per flight cycle</option></select></td><td>${componentInput(index, "base_reserve_rate", component.base_reserve_rate)}</td><td>${componentInput(index, "annual_reserve_escalation", percentInput(component.annual_reserve_escalation), "number", "0.01", "percent")}</td><td>${component.event_driver === "calendar_months" ? '<span class="not-applicable">N/A</span>' : componentInput(index, "usage_since_event_at_lease_start", component.usage_since_event_at_lease_start ?? "")}</td></tr>`).join("")}</tbody></table></div></section>
      <section class="panel form-panel"><div class="panel-header"><div><p class="eyebrow">Monthly exceptions</p><h3>Utilization overrides</h3></div><button type="button" class="button secondary compact" id="add-override">Add month</button></div><div id="override-list" class="override-list">${caseInputs.utilization_overrides.length ? caseInputs.utilization_overrides.map((override, index) => `<div class="override-row"><label class="field"><span>Month end</span><input type="date" data-override-index="${index}" data-override-field="month_end" value="${escapeHtml(override.month_end)}"></label><label class="field"><span>Flight hours</span><input type="number" min="0" step="any" data-override-index="${index}" data-override-field="flight_hours" value="${escapeHtml(override.flight_hours)}"></label><label class="field"><span>Flight cycles</span><input type="number" min="0" step="any" data-override-index="${index}" data-override-field="flight_cycles" value="${escapeHtml(override.flight_cycles)}"></label><button type="button" class="remove-button" data-remove-override="${index}" aria-label="Remove utilization override">Remove</button></div>`).join("") : '<div class="empty-state compact-empty">No month-specific overrides. Defaults apply throughout the lease.</div>'}</div></section>
      <div class="form-actions"><p>Running the model recalculates the full historical lease, then returns the forecast period.</p><button type="button" class="button primary large" data-run-from-form>Run Stage 1–4 model</button></div>
    </form>`;
}

function renderAssumptionsV2() {
  const caseInputs = draftCase;
  const sourceComponents = ["6Y", "12Y", "LDG", "E1"].map((code) => {
    const index = caseInputs.components.findIndex((component) => component.code === code);
    return { component: caseInputs.components[index], index, engineShared: code === "E1" };
  });
  const engineSync = (shared) => shared ? 'data-sync-engine="true"' : "";
  const driverSelect = (component, index, shared) => `<select data-component-index="${index}" data-component-field="event_driver" ${engineSync(shared)}><option value="calendar_months" ${component.event_driver === "calendar_months" ? "selected" : ""}>Calendar months</option><option value="flight_hours" ${component.event_driver === "flight_hours" ? "selected" : ""}>Flight hours</option><option value="flight_cycles" ${component.event_driver === "flight_cycles" ? "selected" : ""}>Flight cycles</option></select>`;
  const basisSelect = (component, index, shared) => `<select data-component-index="${index}" data-component-field="reserve_basis" ${engineSync(shared)}><option value="per_month" ${component.reserve_basis === "per_month" ? "selected" : ""}>Per month</option><option value="per_flight_hour" ${component.reserve_basis === "per_flight_hour" ? "selected" : ""}>Per flight hour</option><option value="per_flight_cycle" ${component.reserve_basis === "per_flight_cycle" ? "selected" : ""}>Per flight cycle</option></select>`;
  const sourceName = (component, shared) => shared ? "Engine Performance Restoration" : component.name;
  const sourceCode = (component, shared) => shared ? "E1 / E2" : component.code;

  return `${heading("Source data", "Inputs & assumptions", "Illustrative inputs are grouped by aircraft, maintenance program and lease terms. Changes are saved locally until the model is run.", `<span class="draft-badge ${isDirty ? "visible" : ""}">Unsaved calculation changes</span>`)}
    <form id="assumptions-form" autocomplete="off">
      <section class="panel form-panel raw-data-section">
        <div class="panel-header"><div><p class="eyebrow">Input group 1</p><h3>Aircraft Description</h3></div><span class="source-badge">Illustrative inputs</span></div>
        <div class="form-grid five">${inputField("Type", "aircraft_type", caseInputs.aircraft_type)}${inputField("Date of Manufacture", "date_of_manufacture", caseInputs.date_of_manufacture, "date")}${inputField("Lessee", "lessee", caseInputs.lessee)}${inputField("Historic / Future FH per Month", "default_monthly_fh", caseInputs.default_monthly_fh, "number", 'min="0" step="any"')}${inputField("Historic / Future FC per Month", "default_monthly_fc", caseInputs.default_monthly_fc, "number", 'min="0" step="any"')}</div>
      </section>

      <section class="panel form-panel raw-data-section">
        <div class="panel-header"><div><p class="eyebrow">Input group 2</p><h3>Aircraft Maintenance Program Information</h3></div><span class="panel-note">Technical cost assumptions · annual escalation</span></div>
        <div class="table-scroll assumption-table source-table"><table><thead><tr><th>Maintenance item</th><th>Event driver</th><th class="number">Interval</th><th class="number">Base cost</th><th class="number">Yearly cost escalation</th></tr></thead><tbody>${sourceComponents.map(({ component, index, engineShared }) => `<tr><td><strong class="component-code">${escapeHtml(sourceCode(component, engineShared))}</strong><span class="component-name">${escapeHtml(sourceName(component, engineShared))}</span></td><td>${driverSelect(component, index, engineShared)}</td><td>${componentInput(index, "interval", component.interval, "number", "any", "", engineSync(engineShared))}</td><td>${componentInput(index, "base_cost", component.base_cost, "number", "any", "", engineSync(engineShared))}</td><td>${componentInput(index, "annual_cost_escalation", percentInput(component.annual_cost_escalation), "number", "0.01", "percent", engineSync(engineShared))}</td></tr>`).join("")}</tbody></table></div>
        <div class="assumption-footnote">V1 treats base maintenance costs as manufacture-year values and escalates them from the aircraft manufacture year. A common Engine Performance Restoration assumption is applied to E1 and E2.</div>
      </section>

      <section class="panel form-panel raw-data-section">
        <div class="panel-header"><div><p class="eyebrow">Input group 3</p><h3>Aircraft Lease Terms</h3></div><span class="source-badge">Contractual inputs</span></div>
        <div class="contract-subsection"><div class="subsection-heading"><span>3.1</span><div><strong>Lease Period</strong><small>Contract dates and analysis cut-off</small></div></div><div class="form-grid three-inputs">${inputField("Lease Start Date", "lease_start_date", caseInputs.lease_start_date, "date")}${inputField("Lease Expiry Date", "lease_expiry_date", caseInputs.lease_expiry_date, "date")}${inputField("Analysis Date", "analysis_date", caseInputs.analysis_date, "date")}</div></div>
        <div class="contract-subsection reserve-terms"><div class="subsection-heading"><span>3.2</span><div><strong>Maintenance Reserve Terms</strong><small>Contracted rates, charging bases and annual escalation</small></div></div><div class="table-scroll assumption-table source-table"><table><thead><tr><th>Maintenance item</th><th>Reserve basis</th><th class="number">Base reserve rate</th><th class="number">Yearly reserve escalation</th></tr></thead><tbody>${sourceComponents.map(({ component, index, engineShared }) => `<tr><td><strong class="component-code">${escapeHtml(sourceCode(component, engineShared))}</strong><span class="component-name">${escapeHtml(sourceName(component, engineShared))}</span></td><td>${basisSelect(component, index, engineShared)}</td><td>${componentInput(index, "base_reserve_rate", component.base_reserve_rate, "number", "any", "", engineSync(engineShared))}</td><td>${componentInput(index, "annual_reserve_escalation", percentInput(component.annual_reserve_escalation), "number", "0.01", "percent", engineSync(engineShared))}</td></tr>`).join("")}</tbody></table></div></div>
        <div class="assumption-footnote">V1 treats the displayed reserve rates as lease-commencement rates and escalates them from the Lease Start Date.</div>
      </section>

      <section class="panel form-panel">
        <div class="panel-header"><div><p class="eyebrow">Scenario controls</p><h3>Monthly utilization overrides</h3></div><button type="button" class="button secondary compact" id="add-override">Add month</button></div>
        <div id="override-list" class="override-list">${caseInputs.utilization_overrides.length ? caseInputs.utilization_overrides.map((override, index) => `<div class="override-row"><label class="field"><span>Month end</span><input type="date" data-override-index="${index}" data-override-field="month_end" value="${escapeHtml(override.month_end)}"></label><label class="field"><span>Flight hours</span><input type="number" min="0" step="any" data-override-index="${index}" data-override-field="flight_hours" value="${escapeHtml(override.flight_hours)}"></label><label class="field"><span>Flight cycles</span><input type="number" min="0" step="any" data-override-index="${index}" data-override-field="flight_cycles" value="${escapeHtml(override.flight_cycles)}"></label><button type="button" class="remove-button" data-remove-override="${index}" aria-label="Remove utilization override">Remove</button></div>`).join("") : '<div class="empty-state compact-empty">No month-specific overrides. Defaults apply throughout the lease.</div>'}</div>
      </section>
      <div class="form-actions"><p>Running the model recalculates the full historical lease, then returns the forecast period.</p><button type="button" class="button primary large" data-run-from-form>Run Stage 1–4 model</button></div>
    </form>`;
}

function renderUtilization() {
  const rows = currentData.utilization;
  const analysisRow = rows[0];
  const expiryRow = rows.at(-1);
  const overrideCount = draftCase.utilization_overrides.length;
  return `${heading("Stage 1", "Aircraft utilization", "Builds monthly FH, FC, TTSN and TCSN from manufacture through lease expiry. Utilization also drives FH/FC-based maintenance events and reserve collections.")}
    <section class="panel utilization-basis"><div class="panel-header"><div><p class="eyebrow">Calculation basis</p><h3>Model inputs used</h3></div><button class="button secondary compact" data-open-view="assumptions">Edit assumptions</button></div><div class="basis-grid"><div><span>Manufacture date</span><strong>${longDate(draftCase.date_of_manufacture)}</strong><small>TTSN / TCSN origin</small></div><div><span>Analysis date</span><strong>${longDate(draftCase.analysis_date)}</strong><small>Forecast opening</small></div><div><span>Lease expiry</span><strong>${longDate(draftCase.lease_expiry_date)}</strong><small>Forecast endpoint</small></div><div><span>Monthly utilization</span><strong>${number(draftCase.default_monthly_fh)} FH / ${number(draftCase.default_monthly_fc)} FC</strong><small>Historic / future assumption</small></div><div><span>Monthly overrides</span><strong>${overrideCount ? `${overrideCount} month${overrideCount === 1 ? "" : "s"}` : "None"}</strong><small>${overrideCount ? "Applied in schedule" : "Defaults used throughout"}</small></div></div></section>
    <section class="panel utilization-results"><div class="panel-header"><div><p class="eyebrow">Key outputs</p><h3>Utilization checkpoints</h3></div><span class="panel-note">Cumulative since manufacture</span></div><div class="checkpoint-grid"><article><div class="checkpoint-heading"><span>Analysis date</span><time>${longDate(analysisRow.date)}</time></div><div class="usage-pair"><div><strong>${number(analysisRow.ttsn)}</strong><small>FH · TTSN</small></div><div><strong>${number(analysisRow.tcsn)}</strong><small>FC · TCSN</small></div></div></article><article><div class="checkpoint-heading"><span>Lease expiry</span><time>${longDate(expiryRow.date)}</time></div><div class="usage-pair"><div><strong>${number(expiryRow.ttsn)}</strong><small>FH · TTSN</small></div><div><strong>${number(expiryRow.tcsn)}</strong><small>FC · TCSN</small></div></div></article></div></section>
    <section class="panel utilization-schedule"><div class="panel-header"><div><p class="eyebrow">Stage 1 output</p><h3>Forecast utilization schedule</h3></div><div class="schedule-actions"><span class="panel-note">${rows.length} monthly rows · analysis date through lease expiry</span><button class="button secondary compact" data-export="utilization">Export CSV</button></div></div><div class="table-scroll data-table utilization-table"><table><colgroup><col class="date-column"><col class="period-column"><col class="monthly-column"><col class="monthly-column"><col class="total-column"><col class="total-column"></colgroup><thead><tr><th>Date</th><th class="number">Period</th><th class="number">FH / month</th><th class="number">FC / month</th><th class="number">TTSN</th><th class="number">TCSN</th></tr></thead><tbody>${rows.map((row, index) => { const checkpoint = index === 0 ? "Analysis date" : index === rows.length - 1 ? "Lease expiry" : ""; return `<tr class="${checkpoint ? "checkpoint-row" : ""}"><td><strong>${longDate(row.date)}</strong>${checkpoint ? `<span class="row-tag">${checkpoint}</span>` : ""}</td><td class="number">${row.period}</td><td class="number">${number(row.fh_month)}</td><td class="number">${number(row.fc_month)}</td><td class="number cumulative">${number(row.ttsn)}</td><td class="number cumulative">${number(row.tcsn)}</td></tr>`; }).join("")}</tbody></table></div><div class="schedule-note"><strong>Calculation logic</strong><span>TTSN and TCSN roll forward each month from the analysis-date opening position using the monthly FH and FC assumptions.</span></div></section>`;
}

function eventRows() {
  return currentData.maintenance_calendar.filter((row) => row.mx_calendar !== "-");
}

function renderEvents() {
  const events = eventRows();
  const driverLabel = (component) => component.event_driver === "calendar_months" ? "Calendar" : component.event_driver === "flight_hours" ? "Flight hours" : "Flight cycles";
  const intervalLabel = (component) => component.event_driver === "calendar_months" ? `${number(component.interval)} months` : component.event_driver === "flight_hours" ? `${number(component.interval)} FH` : `${number(component.interval)} FC`;
  const componentCounts = draftCase.components.map((component) => ({ component, count: events.reduce((sum, row) => sum + Number(row[`event_count_${component.code}`] || 0), 0) }));
  const totalEvents = componentCounts.reduce((sum, item) => sum + item.count, 0);
  return `${heading("Stage 2", "Maintenance events", "Applies each component's calendar, FH or FC interval to the utilization timeline and identifies threshold-crossing months.")}
    <section class="panel event-basis"><div class="panel-header"><div><p class="eyebrow">Calculation basis</p><h3>Maintenance intervals used</h3></div><button class="button secondary compact" data-open-view="assumptions">Edit assumptions</button></div><div class="event-basis-grid">${draftCase.components.map((component) => `<article><div class="event-component"><span class="component-pill">${escapeHtml(component.code)}</span><div><strong>${escapeHtml(component.name)}</strong><small>${driverLabel(component)} driven</small></div></div><div class="event-interval"><span>Event interval</span><strong>${intervalLabel(component)}</strong></div></article>`).join("")}</div></section>
    <section class="panel event-results"><div class="panel-header"><div><p class="eyebrow">Key outputs</p><h3>Forecast event summary</h3></div><span class="panel-note">${totalEvents} component event${totalEvents === 1 ? "" : "s"} across ${events.length} scheduled month${events.length === 1 ? "" : "s"}</span></div><div class="event-count-grid">${componentCounts.map(({ component, count }) => `<article><span class="component-pill">${escapeHtml(component.code)}</span><div><strong>${count}</strong><small>${escapeHtml(component.name)}</small></div></article>`).join("")}</div><div class="event-timeline-heading"><strong>Scheduled event months</strong><span>Usage shown at each event checkpoint</span></div><div class="event-timeline">${events.length ? events.map((row) => `<article><time>${month(row.date)}</time><strong>${escapeHtml(row.mx_calendar)}</strong><span>${number(row.ttsn)} FH · ${number(row.tcsn)} FC</span></article>`).join("") : '<div class="empty-state compact-empty">No maintenance events fall within the forecast period.</div>'}</div></section>
    <section class="panel event-schedule"><div class="panel-header"><div><p class="eyebrow">Stage 2 output</p><h3>Maintenance calendar schedule</h3></div><div class="schedule-actions"><span class="panel-note">${currentData.maintenance_calendar.length} monthly rows · analysis date through lease expiry</span><button class="button secondary compact" data-export="maintenance_calendar">Export CSV</button></div></div>${simpleTable(["Period", "Date", "FH / month", "FC / month", "TTSN", "TCSN", "Events"], currentData.maintenance_calendar.map((row) => [row.period, longDate(row.date), number(row.fh_month), number(row.fc_month), number(row.ttsn), number(row.tcsn), row.mx_calendar]), [0,2,3,4,5], "event-schedule-table")}<div class="schedule-note"><strong>Calculation logic</strong><span>Each component is tested independently against its configured calendar, FH or FC interval; the event is recorded in the month its threshold is crossed.</span></div></section>`;
}

function componentValue(row, prefix) {
  if (selectedComponent === "All") return row[`total_${prefix}`];
  return row[`${prefix}_${selectedComponent}`];
}

function renderInflows() {
  const rows = currentData.reserve_inflows;
  const total = rows.reduce((sum, row) => sum + Number(row.total_reserve_inflow), 0);
  const average = rows.length ? total / rows.length : 0;
  const basisLabel = (component) => component.reserve_basis === "per_month" ? "Per month" : component.reserve_basis === "per_flight_hour" ? "Per FH" : "Per FC";
  return `${heading("Stage 3", "Maintenance reserve inflow", "Applies each component's escalated contractual reserve rate to its monthly charging basis.")}
    <section class="panel inflow-basis"><div class="panel-header"><div><p class="eyebrow">Calculation basis</p><h3>Maintenance reserve terms used</h3></div><button class="button secondary compact" data-open-view="assumptions">Edit assumptions</button></div><div class="event-basis-grid">${draftCase.components.map((component) => `<article><div class="event-component"><span class="component-pill">${escapeHtml(component.code)}</span><div><strong>${escapeHtml(component.name)}</strong><small>${basisLabel(component)}</small></div></div><div class="event-interval"><span>Base reserve rate</span><strong>${money(component.base_reserve_rate)}${component.reserve_basis === "per_month" ? " / month" : component.reserve_basis === "per_flight_hour" ? " / FH" : " / FC"}</strong><small>${percent(component.annual_reserve_escalation)} annual escalation</small></div></article>`).join("")}</div></section>
    <section class="metric-grid four inflow-metrics">${metric("Forecast reserve inflow", money(total, true), `${rows.length}-month collection`)}${metric("Average monthly inflow", money(average, true), "Across all components")}${metric("Analysis-date inflow", money(rows[0].total_reserve_inflow, true), longDate(rows[0].date))}${metric("Lease-expiry inflow", money(rows.at(-1).total_reserve_inflow, true), longDate(rows.at(-1).date))}</section>
    <section class="panel inflow-schedule"><div class="panel-header"><div><p class="eyebrow">Stage 3 output</p><h3>Monthly maintenance reserve inflow</h3></div><div class="schedule-actions"><span class="panel-note">Component collections and total monthly inflow</span><button class="button secondary compact" data-export="reserve_inflows">Export CSV</button></div></div>${simpleTable(["Date", "Mx event", "6Y", "12Y", "LDG", "E1", "E2", "Total inflow"], rows.map((row) => [longDate(row.date), row.mx_calendar, money(row.reserve_inflow_6Y), money(row.reserve_inflow_12Y), money(row.reserve_inflow_LDG), money(row.reserve_inflow_E1), money(row.reserve_inflow_E2), money(row.total_reserve_inflow)]), [2,3,4,5,6,7], "inflow-schedule-table")}<div class="schedule-note"><strong>Calculation logic</strong><span>Monthly inflow equals the escalated reserve rate multiplied by one month, monthly FH or monthly FC according to each component's contractual charging basis.</span></div></section>`;
}

function renderCashflow() {
  const rows = currentData.cashflows;
  const history = currentData.opening_balance_history || [];
  const historicalEvents = currentData.historical_funding_events || [];
  const inflow = rows.reduce((sum, row) => sum + Number(componentValue(row, "reserve_inflow")), 0);
  const outflow = rows.reduce((sum, row) => sum + Number(componentValue(row, "reserve_outflow")), 0);
  const endBalance = selectedComponent === "All" ? rows.at(-1).total_closing_balance : rows.at(-1)[`closing_balance_${selectedComponent}`];
  const settlementEvents = (selectedComponent === "All" ? currentData.funding_events : currentData.funding_events.filter((event) => event.component === selectedComponent)).map((event) => {
    const row = rows.find((item) => item.date === event.event_date);
    return { ...event, opening: event.opening_reserve ?? row[`opening_balance_${event.component}`], inflow: event.current_inflow ?? row[`reserve_inflow_${event.component}`] };
  });
  const historicalSettlementEvents = selectedComponent === "All" ? historicalEvents : historicalEvents.filter((event) => event.component === selectedComponent);
  const shortfall = settlementEvents.reduce((sum, event) => sum + Number(event.shortfall), 0);
  const chartRows = selectedComponent === "All" ? rows : rows.map((row) => ({ ...row, total_reserve_inflow: row[`reserve_inflow_${selectedComponent}`], total_reserve_outflow: row[`reserve_outflow_${selectedComponent}`], total_closing_balance: row[`closing_balance_${selectedComponent}`] }));
  const openingBridge = draftCase.components.map((component) => ({
    component,
    inflow: history.reduce((sum, row) => sum + Number(row[`reserve_inflow_${component.code}`]), 0),
    outflow: history.reduce((sum, row) => sum + Number(row[`reserve_outflow_${component.code}`]), 0),
    opening: Number(rows[0][`opening_balance_${component.code}`]),
  }));
  const historicalInflow = openingBridge.reduce((sum, item) => sum + item.inflow, 0);
  const historicalOutflow = openingBridge.reduce((sum, item) => sum + item.outflow, 0);
  const analysisOpening = openingBridge.reduce((sum, item) => sum + item.opening, 0);
  const componentReconciliation = draftCase.components
    .filter((component) => selectedComponent === "All" || component.code === selectedComponent)
    .map((component) => ({
      component,
      opening: Number(rows[0][`opening_balance_${component.code}`]),
      inflow: rows.reduce((sum, row) => sum + Number(row[`reserve_inflow_${component.code}`]), 0),
      outflow: rows.reduce((sum, row) => sum + Number(row[`reserve_outflow_${component.code}`]), 0),
      closing: Number(rows.at(-1)[`closing_balance_${component.code}`]),
    }));
  const historyValue = (row, field) => selectedComponent === "All" ? row[`total_${field}`] : row[`${field}_${selectedComponent}`];
  return `${heading("Stage 4", "Maintenance event settlement", "")}
    ${reserveAccountSelector()}
    <section class="panel opening-bridge"><div class="panel-header"><div><p class="eyebrow">Historical balance build-up</p><h3>Opening balance bridge</h3></div><span class="panel-note">Lease start through the month before analysis date</span></div><div class="opening-bridge-metrics"><div><span>Historical reserve inflow</span><strong>${money(historicalInflow, true)}</strong><small>${history.length} monthly rows</small></div><div><span>Historical reserve outflow</span><strong>${money(historicalOutflow, true)}</strong><small>Sum of component reimbursements</small></div><div><span>Analysis-date opening balance</span><strong>${money(analysisOpening, true)}</strong><small>Portfolio total · secondary summary</small></div></div>${simpleTable(["Component account", "Lease-start balance", "Historical inflow", "Historical outflow", "Analysis-date opening"], openingBridge.map(({ component, inflow: historicalComponentInflow, outflow: historicalComponentOutflow, opening }) => [component.code, money(0), money(historicalComponentInflow), money(historicalComponentOutflow), money(opening)]), [1,2,3,4], "opening-bridge-table")}<div class="component-event-section"><div class="subsection-header"><div><p class="eyebrow">Account-level drawdowns</p><h4>Historical event settlements</h4></div><span>Each event draws only from its matching component account</span></div>${historicalSettlementEvents.length ? simpleTable(["Event date", "Component account", "Opening reserve", "Current inflow", "Component reserve available", "Event cost", "Component outflow", "Shortfall", "Component closing balance"], historicalSettlementEvents.map((event) => [longDate(event.event_date), event.component, money(event.opening_reserve), money(event.current_inflow), money(event.available_reserve), money(event.event_cost), money(event.reimbursement), event.fully_funded ? "—" : money(event.shortfall), money(event.closing_balance_after_event)]), [2,3,4,5,6,7,8], "historical-settlement-table") : '<div class="empty-state">No historical maintenance events for this component.</div>'}</div><div class="schedule-note account-separation-note"><strong>Segregated reserve accounts</strong><span>Component accounts are segregated; one account’s surplus cannot fund another component’s shortfall.</span></div><details class="history-detail"><summary>View ${history.length}-month historical roll-forward</summary>${simpleTable(["Date", "Events", "Opening balance", "Inflow", "Outflow", "Closing balance"], history.map((row) => [longDate(row.date), row.mx_calendar, money(Number(historyValue(row, "closing_balance")) - Number(historyValue(row, "reserve_inflow")) + Number(historyValue(row, "reserve_outflow"))), money(historyValue(row, "reserve_inflow")), money(historyValue(row, "reserve_outflow")), money(historyValue(row, "closing_balance"))]), [2,3,4,5], "history-rollforward-table")}</details></section>
    <section class="metric-grid four settlement-metrics">${metric("Forecast reserve inflow", money(inflow, true), selectedComponent === "All" ? "All component accounts" : selectedComponent)}${metric("Event reimbursement", money(outflow, true), `${settlementEvents.length} component event${settlementEvents.length === 1 ? "" : "s"}`)}${metric("Funding shortfall", money(shortfall, true), "Event cost not reimbursed", shortfall ? "risk-metric" : "")}${metric("Lease-end balance", money(endBalance, true), `Closing ${selectedComponent === "All" ? "portfolio" : selectedComponent} reserve`)}</section>
    <section class="panel settlement-core"><div class="panel-header"><div><p class="eyebrow">Core decision table</p><h3>Forecast event settlement by component account</h3></div><span class="panel-note">Outflow is the lower of event cost and that component’s reserve available</span></div>${settlementEvents.length ? simpleTable(["Event date", "Component account", "Opening reserve", "Current inflow", "Component reserve available", "Event cost", "Component outflow", "Shortfall", "Component closing balance"], settlementEvents.map((event) => [longDate(event.event_date), event.component, money(event.opening), money(event.inflow), money(event.available_reserve), money(event.event_cost), money(event.reimbursement), event.fully_funded ? "—" : money(event.shortfall), money(event.closing_balance_after_event)]), [2,3,4,5,6,7,8], "settlement-table") : '<div class="empty-state">No forecast maintenance events for this component.</div>'}<div class="schedule-note"><strong>Lower-of rule</strong><span>Component reserve available = that account’s opening balance + current inflow. Component outflow = min(component reserve available, event cost). The remaining component balance stays in the same account.</span></div></section>
    <section class="panel component-reconciliation"><div class="panel-header"><div><p class="eyebrow">Account roll-forward</p><h3>Component account reconciliation</h3></div><span class="panel-note">Primary balance view · accounts do not offset one another</span></div>${simpleTable(["Component account", "Analysis-date opening", "Forecast inflow", "Forecast outflow", "Lease-end balance"], componentReconciliation.map(({ component, opening, inflow: componentInflow, outflow: componentOutflow, closing }) => [component.code, money(opening), money(componentInflow), money(componentOutflow), money(closing)]), [1,2,3,4], "component-account-table")}</section>
    <section class="panel balance-chart"><div class="panel-header"><div><p class="eyebrow">${selectedComponent === "All" ? "Secondary portfolio summary" : "Component balance path"}</p><h3>${selectedComponent === "All" ? "Portfolio total balance path" : `${escapeHtml(selectedComponent)} reserve accumulation and event drawdowns`}</h3></div><div class="chart-legend"><span><i class="legend-inflow"></i> Inflow</span><span><i class="legend-outflow"></i> Outflow</span><span><i class="legend-balance"></i> Closing balance</span></div></div>${cashflowChart(chartRows)}</section>
    <section class="panel cashflow-detail"><div class="panel-header"><div><p class="eyebrow">Stage 4 calculation detail</p><h3>${selectedComponent === "All" ? "Consolidated" : escapeHtml(selectedComponent)} monthly inflow, outflow and balance roll-forward</h3></div><div class="schedule-actions"><span class="panel-note">Supporting calculation detail</span><button class="button secondary compact" data-export="cashflows">Export CSV</button></div></div>${simpleTable(["Period", "Date", "Events", "Opening balance", "Inflow", "Available", "Event cost", "Outflow", "Closing balance", "Shortfall"], rows.map((row) => { const code = selectedComponent; return [row.period, longDate(row.date), row.mx_calendar, money(code === "All" ? Number(row.total_closing_balance) - Number(row.total_reserve_inflow) + Number(row.total_reserve_outflow) : row[`opening_balance_${code}`]), money(componentValue(row, "reserve_inflow")), money(code === "All" ? Number(row.total_closing_balance) + Number(row.total_reserve_outflow) : row[`available_balance_${code}`]), money(code === "All" ? row.total_event_cost : row[`event_cost_${code}`]), money(componentValue(row, "reserve_outflow")), money(code === "All" ? row.total_closing_balance : row[`closing_balance_${code}`]), money(code === "All" ? row.total_unfunded_amount : row[`unfunded_amount_${code}`])]; }), [0,3,4,5,6,7,8,9], "cashflow-detail-table")}<div class="schedule-note"><strong>Roll-forward</strong><span>Opening balance + reserve inflow − event outflow = closing balance. Component accounts remain separate throughout the model.</span></div></section>`;
}

function filteredEvents() {
  return selectedComponent === "All" ? currentData.funding_events : currentData.funding_events.filter((event) => event.component === selectedComponent);
}

function renderRisk() {
  const events = [...filteredEvents()].sort((a, b) => a.event_date.localeCompare(b.event_date));
  const riskEvents = events.filter((event) => !event.fully_funded);
  const totalShortfall = riskEvents.reduce((sum, event) => sum + Number(event.shortfall), 0);
  const lowestCoverage = events.reduce((lowest, event) => !lowest || Number(event.coverage_ratio) < Number(lowest.coverage_ratio) ? event : lowest, null);
  const scope = selectedComponent === "All" ? "All component accounts" : `${selectedComponent} account`;
  return `${heading("Funding assessment", "Forecast maintenance reserve adequacy", "", `<button class="button secondary compact" data-export="funding_events">Export CSV</button>`)}
    ${reserveAccountSelector("risk")}
    <section class="metric-grid four risk-summary">${metric("Forecast events", String(events.length), scope)}${metric("Underfunded events", String(riskEvents.length), `${events.length} event${events.length === 1 ? "" : "s"} assessed`, riskEvents.length ? "risk-metric" : "")}${metric("Total shortfall", money(totalShortfall, true), "Uncovered maintenance cost", totalShortfall ? "risk-metric" : "")}${metric("Lowest coverage", lowestCoverage ? percent(lowestCoverage.coverage_ratio) : "—", lowestCoverage ? `${lowestCoverage.component} · ${longDate(lowestCoverage.event_date)}` : "No forecast events")}</section>
    <section class="panel risk-exceptions"><div class="panel-header"><div><p class="eyebrow">Exceptions requiring attention</p><h3>Underfunded maintenance events</h3></div><span class="panel-note">Ordered by forecast event date</span></div>${riskEvents.length ? `<div class="risk-exception-grid">${riskEvents.map((event) => `<article class="risk-exception-card"><div class="risk-exception-heading"><div><span class="component-pill">${escapeHtml(event.component)}</span><h4>${escapeHtml(event.component_name)}</h4></div><time>${longDate(event.event_date)}</time></div><div class="funding-gap"><span>Funding gap</span><strong>${money(event.shortfall)}</strong></div><dl><div><dt>Event cost</dt><dd>${money(event.event_cost)}</dd></div><div><dt>Component reserve available</dt><dd>${money(event.available_reserve)}</dd></div><div><dt>Coverage</dt><dd>${percent(event.coverage_ratio)}</dd></div><div><dt>Post-event reserve</dt><dd>${money(event.closing_balance_after_event)}</dd></div></dl><span class="status underfunded">Funding action required</span></article>`).join("")}</div>` : `<div class="risk-clear-state"><span>✓</span><div><strong>No funding gaps in this view</strong><p>Every forecast event for ${escapeHtml(scope.toLowerCase())} is fully covered by its matching component reserve.</p></div></div>`}</section>
    <section class="panel risk-detail"><div class="panel-header"><div><p class="eyebrow">Complete forecast schedule</p><h3>All event funding outcomes</h3></div><span class="panel-note">Includes funded events and remaining post-event reserve</span></div>${fundingTable(events)}<div class="schedule-note"><strong>Adequacy test</strong><span>Coverage compares event cost with the matching component reserve available on the payment date. Component accounts remain segregated and cannot offset one another.</span></div></section>`;
}

function caseReportInline(value) {
  return escapeHtml(value)
    .replace(/\[verified: ([A-Za-z0-9_:\-.]+)\]/g, '<span class="verified-ref" title="$1">Verified source</span>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function caseReportHtml(markdown) {
  const lines = String(markdown || "").split("\n");
  const output = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const next = lines[index + 1] || "";
    if (line.trim().startsWith("|") && /^\s*\|?[\s:|-]+\|\s*$/.test(next)) {
      const cells = (value) => value.trim().replace(/^\||\|$/g, "").split("|").map((cell) => caseReportInline(cell.trim()));
      const headers = cells(line);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(cells(lines[index]));
        index += 1;
      }
      index -= 1;
      output.push(`<div class="report-table"><table><thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    const safe = caseReportInline(line);
    if (safe.startsWith("# ")) output.push(`<h2>${safe.slice(2)}</h2>`);
    else if (safe.startsWith("## ")) output.push(`<h3>${safe.slice(3)}</h3>`);
    else if (safe.startsWith("### ")) output.push(`<h4>${safe.slice(4)}</h4>`);
    else if (/^---+$/.test(line.trim())) output.push("<hr>");
    else if (safe.startsWith("- ")) output.push(`<div class="report-bullet">${safe.slice(2)}</div>`);
    else output.push(safe ? `<p>${safe}</p>` : '<div class="report-space"></div>');
  }
  return output.join("");
}

function renderAnalysis() {
  const suggestedQuestions = [
    "Which maintenance events create the greatest funding exposure for the lessor?",
    "Which component reserve rates appear misaligned with forecast maintenance costs?",
    "How does the next engine interval affect the lessor’s reimbursement exposure?",
    "What should the lessor review before lease expiry?",
  ];
  const reportLabels = {
    full_analysis: "Full Maintenance Reserve Analysis",
    funding_adequacy: "Funding Adequacy Review",
    component_rate_review: "Component Reserve-Rate Review",
    engine_interval_sensitivity: "Engine Interval Sensitivity Note",
  };
  const canGenerate = !isDirty && !caseReportRunning && (analysisMode === "report" || analysisQuestion.trim().length > 0);
  const resultTitle = caseReport?.mode === "question" ? "Evidence-based answer" : reportLabels[caseReport?.report_type] || "Generated analysis";
  return `${heading("Lessor analysis workspace", "Analysis & Q&A", "Generate a report or ask a question about the current validated model run.")}
    <section class="panel analysis-usage-guide"><div class="analysis-guide-heading"><div><p class="eyebrow">How to use this workspace</p><h3>Calculated first. Interpreted second.</h3></div><span class="status funded">Current run validated</span></div><div class="analysis-steps"><article><span>01</span><div><strong>Run the model</strong><p>Complete or update Inputs & Assumptions, then run Stage 1–4. Analysis always uses the latest validated results.</p></div></article><article><span>02</span><div><strong>Choose an analysis path</strong><p>Generate a structured report or ask a specific question about funding, reserve rates, events or engine timing.</p></div></article><article><span>03</span><div><strong>Review verified evidence</strong><p>Financial values are bound to deterministic claims. Unsupported calculations are blocked before publication.</p></div></article></div><div class="analysis-boundary"><strong>When a new calculation is required</strong><span>If your question changes utilization, rates, dates, intervals or another assumption, edit the inputs and rerun the model first. The language model does not create new cash-flow results.</span></div></section>
    <section class="analysis-mode-tabs" role="group" aria-label="Choose analysis mode"><button type="button" data-analysis-mode="report" class="${analysisMode === "report" ? "selected" : ""}"><strong>Generate report</strong><small>Structured review of the current run</small></button><button type="button" data-analysis-mode="question" class="${analysisMode === "question" ? "selected" : ""}"><strong>Ask a question</strong><small>Focused answer from verified evidence</small></button></section>
    ${analysisMode === "report" ? `<section class="panel analysis-controls"><div class="analysis-control-copy"><p class="eyebrow">Report builder</p><h3>Select an analysis format</h3><p>Each report uses the same current-run evidence but organizes the interpretation for a different review purpose.</p></div><label class="field analysis-report-select"><span>Report type</span><select data-analysis-report-type>${Object.entries(reportLabels).map(([value, label]) => `<option value="${value}" ${analysisReportType === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select></label><button class="button primary" data-generate-analysis ${canGenerate ? "" : "disabled"}>${caseReportRunning ? "Generating…" : "Generate report"}</button></section>` : `<section class="panel analysis-question-panel"><div class="analysis-control-copy"><p class="eyebrow">Evidence-grounded Q&A</p><h3>Ask about the current model results</h3><p>Questions can address funding exposure, component adequacy, event timing and lessor considerations within the calculated scope.</p></div><label class="analysis-question-field"><span>Your question</span><textarea data-analysis-question maxlength="1200" placeholder="e.g. Which component accounts should the lessor review first?">${escapeHtml(analysisQuestion)}</textarea><small>${analysisQuestion.length} / 1,200 characters</small></label><div class="suggested-question-block"><span>Suggested questions</span><div>${suggestedQuestions.map((question) => `<button type="button" data-suggested-question="${escapeHtml(question)}">${escapeHtml(question)}</button>`).join("")}</div></div><div class="analysis-question-actions"><span>Answers are limited to the current validated run.</span><button class="button primary" data-generate-analysis ${canGenerate ? "" : "disabled"}>${caseReportRunning ? "Analyzing…" : "Analyze question"}</button></div></section>`}
    ${caseReportError ? `<section class="status-banner error" role="alert"><div><strong>Analysis could not be generated</strong><p>${escapeHtml(caseReportError)}</p></div></section>` : ""}
    ${isDirty ? '<div class="note"><strong>Calculation required.</strong> Inputs have changed. Run the updated Stage 1–4 model before generating analysis so the evidence matches the displayed assumptions.</div>' : ""}
    ${caseReport ? `<section class="panel case-report-output"><div class="panel-header"><div><p class="eyebrow">Generated analysis</p><h3>${escapeHtml(resultTitle)}</h3>${caseReport.question ? `<p class="analysis-result-question">${escapeHtml(caseReport.question)}</p>` : ""}</div><span class="status funded">Verified evidence</span></div><article class="case-report-prose">${caseReportHtml(caseReport.report_markdown)}</article><div class="case-report-audit"><span>${escapeHtml(caseReport.model_id)}</span><span>English</span><span>Lessor perspective</span><span>${number(caseReport.verified_claim_count)} verified claims</span><span>${number(caseReport.financial_numbers_checked)} financial references checked</span><span>${escapeHtml(caseReport.guardrail_status)}</span>${caseReport.removed_line_count ? `<span>${number(caseReport.removed_line_count)} unsupported lines removed</span>` : ""}</div></section>` : '<section class="panel case-report-empty"><div class="empty-state">No report or answer has been generated in this session.</div></section>'}
    <div class="note"><strong>Analysis boundary.</strong> The workspace covers maintenance reserve funding. Base rent, NPV, aircraft market value, downtime, lessee credit quality and collectability are outside the current V1 model.</div>`;
}

function renderAudit() {
  const checks = currentData.audit.runtime_checks;
  const reconciliation = currentData.audit.demo_reconciliation;
  const checkEntries = Object.entries(checks);
  const totalAssertions = checkEntries.reduce((sum, [, check]) => sum + Number(check.checks), 0);
  const passedAssertions = checkEntries.reduce((sum, [, check]) => sum + Number(check.passed_checks), 0);
  const failedRules = checkEntries.filter(([, check]) => !check.passed);
  const changes = currentData.audit.input_changes || [];
  const stageLabels = { stage_1: "Stage 1 · Utilization", stage_2: "Stage 2 · Maintenance events", stage_3: "Stage 3 · Reserve inflow", stage_4_forecast: "Stage 4 · Forecast settlement", stage_4_history: "Stage 4 · Historical opening build" };
  const parityLabel = reconciliation.applicable ? (reconciliation.status === "matched" ? "Snapshot matched" : "Snapshot mismatch") : "Not applicable";
  const failureRows = failedRules.flatMap(([key, check]) => (check.failures || []).map((failure) => [check.label || key.replaceAll("_", " "), longDate(failure.date), failure.component, failure.expected, failure.actual, failure.difference ?? "—"]));
  const displayInput = (value) => value === null || value === undefined || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
  return `${heading("Model validation", "Model assurance & reconciliation", "Runtime checks cover the complete lease history and forecast. The default demo is also compared with a versioned regression snapshot.", `<button class="button secondary compact" data-export-validation>Export validation</button>`)}
    <section class="metric-grid four validation-summary">${metric("Model status", currentData.run.status === "validated" ? "Validated" : "Failed", `${failedRules.length} failed validation rules`, failedRules.length ? "risk-metric" : "")}${metric("Runtime assertions", number(passedAssertions), `${number(totalAssertions)} passed across the lease period`)}${metric("Snapshot regression", parityLabel, reconciliation.applicable ? `${Object.keys(reconciliation.stages).length} datasets checked` : "Scenario inputs differ")}${metric("Input changes", String(changes.length), currentData.run.demo_case ? "Default inputs unchanged" : "Versus default demo")}</section>
    <section class="panel run-identity"><div class="panel-header"><div><p class="eyebrow">Run identity</p><h3>Calculation record</h3></div><span class="status ${currentData.run.status === "validated" ? "funded" : "underfunded"}">${escapeHtml(currentData.run.status)}</span></div><div class="run-identity-grid"><div><span>Calculated at</span><strong>${dateTime(currentData.run.calculated_at)}</strong></div><div><span>Model version</span><strong>${escapeHtml(currentData.run.model_version)}</strong></div><div><span>Run type</span><strong>${currentData.run.demo_case ? "Default demo" : "User scenario"}</strong></div><div><span>Calculation engine</span><strong>Deterministic Python engine</strong></div><div><span>Run ID</span><strong class="mono-value">${escapeHtml(currentData.run.run_id)}</strong></div><div><span>Input signature</span><strong class="mono-value">${escapeHtml(currentData.run.input_signature)}</strong></div></div></section>
    <section class="panel runtime-validation"><div class="panel-header"><div><p class="eyebrow">Runtime integrity</p><h3>Historical and forecast calculation checks</h3></div><span class="panel-note">${currentData.audit.runtime_scope.months} months · ${currentData.audit.runtime_scope.component_accounts} component accounts</span></div><div class="validation-check-list">${checkEntries.map(([, check]) => `<article><span class="audit-icon ${check.passed ? "passed" : "failed"}">${check.passed ? "✓" : "!"}</span><div><strong>${escapeHtml(check.label)}</strong><p>${escapeHtml(check.description)}</p></div><div class="validation-count"><strong>${number(check.passed_checks)} / ${number(check.checks)}</strong><span>${check.passed ? "Passed" : "Failed"}</span></div></article>`).join("")}</div>${failureRows.length ? `<details class="validation-failures"><summary>View ${failureRows.length} recorded failure details</summary>${simpleTable(["Rule", "Date", "Account / total", "Expected", "Calculated", "Difference"], failureRows, [3,4,5], "validation-failure-table")}</details>` : '<div class="validation-clear"><span>✓</span><p>All runtime assertions passed. No failure details were generated.</p></div>'}</section>
    <section class="panel workbook-reconciliation"><div class="panel-header"><div><p class="eyebrow">Regression evidence</p><h3>${reconciliation.applicable ? (reconciliation.status === "matched" ? "Demonstration outputs matched" : "Regression differences detected") : "Snapshot comparison not applicable"}</h3></div><span class="status ${reconciliation.status === "matched" ? "funded" : reconciliation.applicable ? "underfunded" : "neutral"}">${escapeHtml(reconciliation.status.replaceAll("_", " "))}</span></div><div class="reconciliation-source"><div><span>Scenario</span><strong>${escapeHtml(reconciliation.scenario_name)}</strong></div><div><span>Evidence basis</span><strong>${escapeHtml(reconciliation.evidence)}</strong></div><div><span>Numeric tolerance</span><strong>${escapeHtml(reconciliation.numeric_tolerance)}</strong></div></div>${reconciliation.applicable ? simpleTable(["Model output", "Dataset", "Rows matched", "Columns checked", "Maximum difference", "Status"], Object.entries(reconciliation.stages).map(([stage, result]) => [stageLabels[stage] || stage, result.dataset, `${result.matched_rows} / ${result.snapshot_rows}`, result.checked_columns, Number(result.max_numeric_difference).toExponential(2), result.matched ? "Matched" : "Failed"]), [2,3,4], "workbook-reconciliation-table") : `<div class="reconciliation-message"><p>${escapeHtml(reconciliation.reason)}</p><span>Runtime integrity checks remain fully applicable to this scenario.</span></div>`}</section>
    <section class="panel input-change-panel"><div class="panel-header"><div><p class="eyebrow">Input provenance</p><h3>Changes from default demo</h3></div><span class="panel-note">Scalar input comparison</span></div>${changes.length ? simpleTable(["Input field", "Default", "Current scenario"], changes.map((change) => [change.field.replaceAll("_", " "), displayInput(change.default), displayInput(change.scenario)]), [], "input-change-table") : '<div class="validation-clear"><span>✓</span><p>No input changes. This run uses the versioned demonstration assumptions.</p></div>'}</section>
    <section class="panel methodology"><div class="panel-header"><div><p class="eyebrow">Calculation lineage</p><h3>Deterministic Stage 1–4 sequence</h3></div><span class="panel-note">Traceable monthly calculations</span></div><ol><li><span>01</span><div><strong>Utilization</strong><p>Monthly FH and FC produce cumulative TTSN and TCSN.</p></div></li><li><span>02</span><div><strong>Maintenance events</strong><p>Component thresholds determine historical and forecast event months.</p></div></li><li><span>03</span><div><strong>Reserve collections</strong><p>Contract rates, escalation and usage produce account-level inflows.</p></div></li><li><span>04</span><div><strong>Settlement and balances</strong><p>Historical openings and exact lower-of reimbursements produce component balances and shortfalls.</p></div></li></ol></section>`;
}

function auditStrip() {
  const checks = Object.values(currentData.audit.runtime_checks);
  const total = checks.reduce((sum, check) => sum + Number(check.checks), 0);
  const passed = checks.reduce((sum, check) => sum + Number(check.passed_checks), 0);
  return `<section class="audit-strip"><div><p class="eyebrow">Model assurance</p><strong>Runtime verification</strong></div>${["Stage 1", "Stage 2", "Stage 3", "Stage 4"].map((stage) => `<div class="audit-check"><span>✓</span><div><strong>${stage}</strong><small>${currentData.summary.forecast_months} forecast rows</small></div></div>`).join("")}<div class="audit-check tests"><span>✓</span><div><strong>Assertions</strong><small>${number(passed)} / ${number(total)} passed</small></div></div></section>`;
}

function simpleTable(headers, rows, numericColumns = [], className = "") {
  return `<div class="table-scroll data-table ${escapeHtml(className)}"><table><thead><tr>${headers.map((header, index) => `<th class="${numericColumns.includes(index) ? "number" : ""}">${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell, index) => `<td class="${numericColumns.includes(index) ? "number" : ""}">${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function renderCurrentView() {
  if (!VIEWS.includes(currentView)) currentView = "overview";
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === currentView));
  const renderers = { overview: renderOverview, assumptions: renderAssumptionsV2, utilization: renderUtilization, events: renderEvents, inflows: renderInflows, cashflow: renderCashflow, risk: renderRisk, analysis: renderAnalysis, audit: renderAudit };
  document.querySelector("#view-root").innerHTML = renderers[currentView]();
  bindViewActions();
  updateCaseHeader();
}

function navigate(view) {
  currentView = view;
  location.hash = view;
  renderCurrentView();
  document.querySelector("#view-root").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function syncDraftFromForm() {
  document.querySelectorAll("[data-case-field]").forEach((input) => { draftCase[input.dataset.caseField] = input.value; });
  document.querySelectorAll("[data-component-field]").forEach((input) => {
    const component = draftCase.components[Number(input.dataset.componentIndex)];
    let value = input.value;
    if (input.dataset.transform === "percent") value = String(Number(input.value) / 100);
    component[input.dataset.componentField] = value === "" && ["last_event_date", "usage_since_event_at_lease_start"].includes(input.dataset.componentField) ? null : value;
    if (input.dataset.syncEngine === "true") {
      const engineTwo = draftCase.components.find((item) => item.code === "E2");
      engineTwo[input.dataset.componentField] = component[input.dataset.componentField];
    }
  });
  document.querySelectorAll("[data-override-field]").forEach((input) => { draftCase.utilization_overrides[Number(input.dataset.overrideIndex)][input.dataset.overrideField] = input.value; });
  applyV1DerivedBaseDates(draftCase);
  saveDraft();
  updateCaseHeader();
}

function applyV1DerivedBaseDates(caseInputs) {
  if (!caseInputs?.components) return caseInputs;
  caseInputs.components.forEach((component) => {
    component.cost_base_date = caseInputs.date_of_manufacture;
    component.reserve_rate_base_date = caseInputs.lease_start_date;
  });
  return caseInputs;
}

function bindViewActions() {
  document.querySelectorAll("[data-open-view]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.openView)));
  document.querySelectorAll("[data-component]").forEach((button) => button.addEventListener("click", () => { selectedComponent = button.dataset.component; renderCurrentView(); }));
  document.querySelectorAll("[data-export]").forEach((button) => button.addEventListener("click", () => exportCsv(button.dataset.export)));
  document.querySelectorAll("[data-export-validation]").forEach((button) => button.addEventListener("click", exportValidation));
  document.querySelectorAll("[data-analysis-mode]").forEach((button) => button.addEventListener("click", () => { analysisMode = button.dataset.analysisMode; caseReport = null; caseReportError = ""; renderCurrentView(); }));
  document.querySelectorAll("[data-generate-analysis]").forEach((button) => button.addEventListener("click", generateV1Analysis));
  document.querySelectorAll("[data-suggested-question]").forEach((button) => button.addEventListener("click", () => { analysisQuestion = button.dataset.suggestedQuestion; caseReport = null; renderCurrentView(); }));
  const reportType = document.querySelector("[data-analysis-report-type]");
  if (reportType) reportType.addEventListener("change", (event) => { analysisReportType = event.target.value; caseReport = null; });
  const questionInput = document.querySelector("[data-analysis-question]");
  if (questionInput) questionInput.addEventListener("input", (event) => { analysisQuestion = event.target.value; caseReport = null; const count = event.target.parentElement.querySelector("small"); if (count) count.textContent = `${analysisQuestion.length} / 1,200 characters`; const button = document.querySelector("[data-generate-analysis]"); if (button) button.disabled = isDirty || caseReportRunning || !analysisQuestion.trim(); });
  if (currentView !== "assumptions") return;
  const form = document.querySelector("#assumptions-form");
  form.addEventListener("input", syncDraftFromForm);
  form.addEventListener("change", (event) => {
    syncDraftFromForm();
    if (event.target.dataset.componentField === "event_driver") renderCurrentView();
  });
  document.querySelector("#add-override").addEventListener("click", () => {
    syncDraftFromForm();
    draftCase.utilization_overrides.push({ month_end: draftCase.analysis_date, flight_hours: draftCase.default_monthly_fh, flight_cycles: draftCase.default_monthly_fc });
    saveDraft();
    renderCurrentView();
  });
  document.querySelectorAll("[data-remove-override]").forEach((button) => button.addEventListener("click", () => {
    syncDraftFromForm();
    draftCase.utilization_overrides.splice(Number(button.dataset.removeOverride), 1);
    saveDraft();
    renderCurrentView();
  }));
  document.querySelector("[data-run-from-form]").addEventListener("click", runModel);
}

async function generateV1Analysis() {
  if (caseReportRunning || isDirty) return;
  caseReportRunning = true;
  caseReportError = "";
  caseReport = null;
  renderCurrentView();
  try {
    const payload = { case: currentData.case, mode: analysisMode };
    if (analysisMode === "report") payload.report_type = analysisReportType;
    else payload.question = analysisQuestion.trim();
    const response = await fetch("/api/v1/analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let message = "Bedrock analysis request failed.";
      try {
        const error = await response.json();
        message = error.message || message;
      } catch {}
      throw new Error(message);
    }
    caseReport = await response.json();
    showToast(analysisMode === "report" ? "Verified report generated." : "Evidence-based answer generated.");
  } catch (error) {
    caseReportError = location.protocol.startsWith("http") ? error.message : "Start the local Python service to use Bedrock analysis.";
  } finally {
    caseReportRunning = false;
    renderCurrentView();
  }
}

async function runModel() {
  if (currentView === "assumptions") syncDraftFromForm();
  const buttons = document.querySelectorAll("#run-model, [data-run-from-form]");
  buttons.forEach((button) => { button.disabled = true; button.textContent = "Calculating…"; });
  try {
    const response = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case: draftCase }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "The model rejected these inputs.");
    currentData = payload;
    draftCase = structuredClone(payload.case);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(draftCase));
    isDirty = false;
    selectedComponent = "All";
    caseReport = null;
    caseReportError = "";
    showToast("Stage 1–4 recalculated successfully.");
    navigate("overview");
  } catch (error) {
    const message = location.protocol === "file:" ? "Start the local Python service to run edited scenarios." : error.message;
    showToast(message, "error");
    buttons.forEach((button) => { button.disabled = false; });
    renderCurrentView();
  }
}

function downloadFile(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function exportRun() {
  downloadFile(`aircraft-reserve-${currentData.run.run_id}.json`, JSON.stringify(currentData, null, 2), "application/json");
  showToast("Current model run exported.");
}

function exportValidation() {
  const report = { run: currentData.run, audit: currentData.audit };
  downloadFile(`model-validation-${currentData.run.run_id}.json`, JSON.stringify(report, null, 2), "application/json");
  showToast("Validation report exported.");
}

function exportCsv(section) {
  const rows = currentData[section];
  if (!Array.isArray(rows) || !rows.length) return;
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const csv = [headers.join(","), ...rows.map((row) => headers.map((header) => `"${String(row[header] ?? "").replaceAll('"', '""')}"`).join(","))].join("\n");
  downloadFile(`${section}-${currentData.run.run_id}.csv`, csv, "text/csv;charset=utf-8");
  showToast(`${section.replaceAll("_", " ")} exported.`);
}

function resetDemo() {
  draftCase = structuredClone(demoData.case);
  currentData = structuredClone(demoData);
  localStorage.removeItem(STORAGE_KEY);
  isDirty = false;
  selectedComponent = "All";
  caseReport = null;
  caseReportError = "";
  showToast("Demo scenario restored.");
  navigate("assumptions");
}

document.querySelector("#model-navigation").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) navigate(button.dataset.view);
});
document.querySelector("#run-model").addEventListener("click", runModel);
document.querySelector("#export-data").addEventListener("click", exportRun);
document.querySelector("#reset-case").addEventListener("click", resetDemo);
window.addEventListener("hashchange", () => { const view = location.hash.slice(1); if (view && view !== currentView) { currentView = view; renderCurrentView(); } });

renderCurrentView();
