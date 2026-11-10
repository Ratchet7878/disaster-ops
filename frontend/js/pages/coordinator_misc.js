// Missions, Vehicles, Resources (warehouses), Roads & Weather, and Audit
// Log pages.

async function renderCoordinatorMissions(params, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const missions = await Api.listMissions();
  container.innerHTML = `
    <div class="eyebrow">Operations</div>
    <h1 class="section-heading mb-16">Missions</h1>
    <div class="card">
      ${missions.length === 0 ? '<p class="muted small">No missions yet — approve a recommendation to dispatch one.</p>' : `
      <table>
        <thead><tr><th>Mission</th><th>Resource</th><th>Qty</th><th>Vehicle</th><th>Source</th><th>Destination</th><th>Status</th><th>ETA</th></tr></thead>
        <tbody>
          ${missions.map((m) => `
            <tr>
              <td class="mono small">${m.mission_id}</td>
              <td>${titleCase(m.resource_type)}</td>
              <td>${fmtQty(m.quantity_canonical, m.unit)}</td>
              <td class="mono">${m.vehicle_id}</td>
              <td class="small">${m.source_type === 'WAREHOUSE' ? m.source_id : m.source_id}</td>
              <td class="small">${m.destination_shelter_id}</td>
              <td>${statusPill(m.status)}</td>
              <td>${m.status === 'DELIVERED' ? fmtDateTime(m.delivered_at) : fmtMinutes(m.eta_minutes)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>`}
    </div>
  `;
}

function statusPill(status) {
  const colors = { DISPATCHED: 'var(--info)', IN_TRANSIT: 'var(--info)', DELAYED: 'var(--warn)', DELIVERED: 'var(--ok)', CANCELLED: 'var(--ink-400)' };
  return `<span style="color:${colors[status] || 'inherit'};font-weight:600;">${titleCase(status)}</span>`;
}

async function renderCoordinatorVehicles(params, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const vehicles = await Api.listVehicles();
  container.innerHTML = `
    <div class="eyebrow">Resources</div>
    <h1 class="section-heading mb-16">Vehicles</h1>
    <div class="card">
      <table>
        <thead><tr><th>Vehicle</th><th>Capacity</th><th>Home base</th><th>Status</th><th>Available at</th></tr></thead>
        <tbody>
          ${vehicles.map((v) => `
            <tr>
              <td><strong>${escapeHtml(v.name)}</strong></td>
              <td>${fmtQty(v.capacity_canonical, v.unit)}</td>
              <td class="mono small">${v.home_base_id || '—'}</td>
              <td>${statusPill(v.status)}</td>
              <td class="small muted">${v.available_at ? fmtDateTime(v.available_at) : '—'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

async function renderCoordinatorResources(params, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const warehouses = await Api.listResources();
  container.innerHTML = `
    <div class="eyebrow">Resources</div>
    <h1 class="section-heading mb-16">Warehouses</h1>
    <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));">
      ${warehouses.map((wh) => `
        <div class="card">
          <div class="card-title">${escapeHtml(wh.name)}</div>
          <table>
            <thead><tr><th>Resource</th><th>On hand</th><th>Reserve</th><th>Committed</th><th>Transferable</th></tr></thead>
            <tbody>
              ${wh.inventory.map((i) => {
                const transferable = i.quantity_on_hand_canonical - i.reserve_quantity_canonical - i.committed_quantity_canonical;
                return `<tr>
                  <td>${titleCase(i.resource_type)}</td>
                  <td>${fmtQty(i.quantity_on_hand_canonical, i.unit)}</td>
                  <td class="muted">${fmtQty(i.reserve_quantity_canonical, i.unit)}</td>
                  <td class="muted">${fmtQty(i.committed_quantity_canonical, i.unit)}</td>
                  <td style="color:${transferable <= 0 ? 'var(--danger)' : 'var(--ok)'}">${fmtQty(transferable, i.unit)}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
      `).join('')}
    </div>
  `;
}

async function renderCoordinatorRoads(params, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const [roads, weather] = await Promise.all([Api.listRoads(), Api.getWeather()]);

  container.innerHTML = `
    <div class="eyebrow">Resources</div>
    <h1 class="section-heading mb-16">Roads &amp; Weather</h1>

    <div class="card mb-16">
      <div class="card-title">Weather</div>
      ${weather ? `
        <div class="flex gap-16">
          <div><div class="eyebrow">Weather risk</div><strong>${Math.round(weather.weather_risk * 100)}%</strong></div>
          <div><div class="eyebrow">Obstruction risk</div><strong>${Math.round(weather.obstruction_risk * 100)}%</strong></div>
          <div><div class="eyebrow">Travel allowed</div><strong>${weather.travel_allowed ? 'Yes' : 'No'}</strong></div>
        </div>
      ` : '<p class="muted small">No weather snapshot available.</p>'}
    </div>

    <div class="card">
      <div class="flex-between mb-12">
        <div class="card-title" style="margin-bottom:0;">Road Segments</div>
      </div>
      <p class="small muted mb-16">Simulate an event to see DisasterOps automatically invalidate affected recommendations and generate replacements (spec section 175, "Event-Driven Replanning").</p>
      <table>
        <thead><tr><th>Segment</th><th>Name</th><th>Status</th><th>Updated</th><th></th></tr></thead>
        <tbody id="roads-tbody">
          ${roads.map((r) => `
            <tr>
              <td class="mono small">${r.road_segment_id}</td>
              <td>${escapeHtml(r.name)}</td>
              <td>${roadStatusPill(r.status)}</td>
              <td class="small muted">${timeAgo(r.last_updated_at)}</td>
              <td>
                ${r.status !== 'BLOCKED'
                  ? `<button class="btn btn-danger block-btn" data-seg="${r.road_segment_id}">Simulate closure</button>`
                  : `<button class="btn reopen-btn" data-seg="${r.road_segment_id}">Reopen</button>`}
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div id="replan-result"></div>
  `;

  document.querySelectorAll('.block-btn').forEach((btn) => {
    btn.addEventListener('click', () => triggerRoadEvent(btn.dataset.seg, 'BLOCKED', params, container));
  });
  document.querySelectorAll('.reopen-btn').forEach((btn) => {
    btn.addEventListener('click', () => triggerRoadEvent(btn.dataset.seg, 'OPEN', params, container));
  });
}

function roadStatusPill(status) {
  const colors = { OPEN: 'var(--ok)', RESTRICTED: 'var(--warn)', UNKNOWN: 'var(--ink-400)', BLOCKED: 'var(--danger)' };
  return `<span style="color:${colors[status]};font-weight:600;">${titleCase(status)}</span>`;
}

async function triggerRoadEvent(segmentId, newStatus, params, container) {
  const resultBox = qs('replan-result');
  resultBox.innerHTML = `<div class="card mt-16"><span class="spinner"></span> Processing event and replanning affected needs…</div>`;
  try {
    const resp = await Api.createRoadEvent({
      road_segment_id: segmentId, new_status: newStatus,
      note: newStatus === 'BLOCKED' ? 'Simulated closure from coordinator dashboard' : 'Simulated reopening',
    });
    toast(newStatus === 'BLOCKED' ? 'Road closure simulated — replanning…' : 'Road reopened', newStatus === 'BLOCKED' ? 'error' : 'success');

    if (resp.replanned.length === 0) {
      resultBox.innerHTML = `<div class="card" style="margin-top:16px;">No active needs were affected by this segment.</div>`;
    } else {
      resultBox.innerHTML = `
        <div class="card" style="margin-top:16px;border-color:var(--accent);">
          <div class="card-title">Automatic Replanning Result</div>
          <p class="small muted mb-12">Affected shelters: ${resp.affected_shelters.join(', ')}</p>
          ${resp.replanned.map((r) => {
            const rec = r.result.recommendation;
            return `
              <div class="list-item">
                <div class="flex-between">
                  <div><strong>${escapeHtml(r.need_id)}</strong> <span class="small muted">urgency ${r.result.urgency.score_display}</span></div>
                  ${rec && !rec.no_acceptable_plan
                    ? `<a href="#/coordinator/needs/${r.need_id}" class="btn btn-primary">New recommendation ready</a>`
                    : `<span class="small" style="color:var(--band-very-high);">No acceptable plan</span>`}
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }
    renderCoordinatorRoads(params, container);
  } catch (err) {
    resultBox.innerHTML = `<div class="card" style="margin-top:16px;color:var(--danger);">${escapeHtml(err.message)}</div>`;
  }
}

async function renderCoordinatorAudit(params, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const audit = await Api.getAudit();
  container.innerHTML = `
    <div class="eyebrow">System</div>
    <h1 class="section-heading mb-16">Audit Log</h1>
    <p class="small muted mb-16">Every decision-relevant event, append-only (spec section 179). ${audit.length} events shown.</p>
    <div class="card">
      <table>
        <thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Object</th><th>State</th><th>Reason</th></tr></thead>
        <tbody>
          ${audit.map((a) => `
            <tr>
              <td class="small mono">${fmtDateTime(a.occurred_at)}</td>
              <td class="small">${titleCase(a.event_type)}</td>
              <td class="small muted">${escapeHtml(a.actor_type + (a.actor_id ? ' · ' + a.actor_id : ''))}</td>
              <td class="small mono muted">${escapeHtml(a.object_id || '—')}</td>
              <td class="small mono muted">${a.state_version_before ?? ''}${a.state_version_after ? ' → ' + a.state_version_after : ''}</td>
              <td class="small muted">${escapeHtml(a.reason_codes || a.explanation || '—')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

window.renderCoordinatorMissions = renderCoordinatorMissions;
window.renderCoordinatorVehicles = renderCoordinatorVehicles;
window.renderCoordinatorResources = renderCoordinatorResources;
window.renderCoordinatorRoads = renderCoordinatorRoads;
window.renderCoordinatorAudit = renderCoordinatorAudit;
