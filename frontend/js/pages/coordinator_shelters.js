// Shelter list + Shelter Detail (spec section 159).

async function renderCoordinatorShelters(params, container) {
  if (params.id) return renderShelterDetail(params.id, container);

  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const [shelters, needs] = await Promise.all([Api.listShelters(), Api.listNeeds()]);
  const needCountByShelter = {};
  needs.forEach((n) => { needCountByShelter[n.shelter_id] = (needCountByShelter[n.shelter_id] || 0) + 1; });

  container.innerHTML = `
    <div class="eyebrow">Operations</div>
    <h1 class="section-heading mb-16">Shelters</h1>
    <div class="grid" style="grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));">
      ${shelters.map((s) => `
        <div class="card row-link" data-shelter="${s.shelter_id}">
          <div class="flex-between mb-8">
            <strong>${escapeHtml(s.name)}</strong>
            <span class="small muted mono">${s.shelter_id}</span>
          </div>
          <div class="small muted mb-12">${s.population_total} people · ${s.vulnerable_total} vulnerable</div>
          <div class="flex-between small">
            <span class="muted">${needCountByShelter[s.shelter_id] || 0} active need(s)</span>
            <span class="muted">Updated ${timeAgo(s.last_report_at)}</span>
          </div>
        </div>
      `).join('')}
    </div>
  `;
  document.querySelectorAll('[data-shelter]').forEach((el) => {
    el.addEventListener('click', () => { location.hash = `#/coordinator/shelters/${el.dataset.shelter}`; });
  });
}

async function renderShelterDetail(shelterId, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const [shelter, allNeeds, allMissions, roads] = await Promise.all([
    Api.getShelter(shelterId), Api.listNeeds(), Api.listMissions(), Api.listRoads(),
  ]);
  const needs = allNeeds.filter((n) => n.shelter_id === shelterId);
  const missions = allMissions.filter((m) => m.destination_shelter_id === shelterId);
  const primaryRoad = roads.find((r) => r.road_segment_id === shelter.road_access.primary_segment_id);
  const secondaryRoad = roads.find((r) => r.road_segment_id === shelter.road_access.secondary_segment_id);

  container.innerHTML = `
    <a href="#/coordinator/shelters" class="small muted" style="text-decoration:none;">&larr; All shelters</a>
    <div class="flex-between mb-16" style="margin-top:6px;">
      <div>
        <div class="eyebrow">Shelter</div>
        <h1 class="section-heading">${escapeHtml(shelter.name)}</h1>
      </div>
      <span class="pill mono">${shelter.shelter_id}</span>
    </div>

    <div class="stat-row">
      <div class="stat-card"><div class="stat-value">${shelter.population_total}</div><div class="stat-label">Population</div></div>
      <div class="stat-card"><div class="stat-value">${shelter.vulnerable_total}</div><div class="stat-label">Vulnerable</div></div>
      <div class="stat-card"><div class="stat-value">${needs.length}</div><div class="stat-label">Active needs</div></div>
      <div class="stat-card"><div class="stat-value">${timeAgo(shelter.last_report_at)}</div><div class="stat-label">Last update</div></div>
    </div>

    <div class="grid" style="grid-template-columns: 1fr 1fr;">
      <div class="card">
        <div class="card-title">Infrastructure</div>
        ${Object.entries(shelter.infrastructure).map(([k, v]) => `
          <div class="flex-between list-item"><span class="muted small">${titleCase(k)}</span><span style="color:${v === 'FAILED' ? 'var(--danger)' : v === 'LIMITED' || v === 'WEAK' ? 'var(--warn)' : 'var(--ok)'}">${titleCase(v)}</span></div>
        `).join('')}
        <div class="divider"></div>
        <div class="flex-between list-item"><span class="muted small">Primary road</span><span>${primaryRoad ? titleCase(primaryRoad.status) : '—'}</span></div>
        ${secondaryRoad ? `<div class="flex-between list-item"><span class="muted small">Secondary road</span><span>${titleCase(secondaryRoad.status)}</span></div>` : ''}
        <div class="flex-between list-item"><span class="muted small">Local coping capacity</span><span>${titleCase(shelter.local_coping_situation)}</span></div>
      </div>

      <div class="card">
        <div class="card-title">Resource Inventory</div>
        <table>
          <thead><tr><th>Resource</th><th>On hand</th><th>Consumption/hr</th></tr></thead>
          <tbody>
            ${shelter.resources.map((r) => `
              <tr><td>${titleCase(r.resource_type)}</td><td>${fmtQty(r.quantity_canonical, r.unit)}</td><td>${r.consumption_per_hour_canonical ? fmtQty(r.consumption_per_hour_canonical, r.unit) : '—'}</td></tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card mb-16" style="margin-top:16px;">
      <div class="card-title">Active Needs</div>
      ${needs.length === 0 ? '<p class="muted small">None right now.</p>' : `
      <table>
        <thead><tr><th>Resource</th><th>Urgency</th><th></th></tr></thead>
        <tbody>
          ${needs.map((n) => `
            <tr><td>${titleCase(n.resource_type)}</td><td>${bandBadge(n.urgency.band, n.urgency.score_display)}</td>
            <td><a href="#/coordinator/needs/${n.need_id}" class="btn">Review</a></td></tr>
          `).join('')}
        </tbody>
      </table>`}
    </div>

    <div class="card">
      <div class="card-title">Deliveries</div>
      ${missions.length === 0 ? '<p class="muted small">No deliveries yet.</p>' : `
      <table>
        <thead><tr><th>Resource</th><th>Qty</th><th>Vehicle</th><th>Status</th><th>ETA</th></tr></thead>
        <tbody>
          ${missions.map((m) => `
            <tr><td>${titleCase(m.resource_type)}</td><td>${fmtQty(m.quantity_canonical, m.unit)}</td><td class="mono">${m.vehicle_id}</td><td>${titleCase(m.status)}</td><td>${fmtMinutes(m.eta_minutes)}</td></tr>
          `).join('')}
        </tbody>
      </table>`}
    </div>
  `;
}

window.renderCoordinatorShelters = renderCoordinatorShelters;
