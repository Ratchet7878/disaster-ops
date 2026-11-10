// Coordinator Dashboard (spec section 154.1): shelter overview, map,
// priority needs, AI recommendation for the top need, active missions.

async function renderCoordinatorDashboard(params, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

  const [shelters, needs, missions, vehicles, roads] = await Promise.all([
    Api.listShelters(), Api.listNeeds(), Api.listMissions(), Api.listVehicles(), Api.listRoads(),
  ]);
  const municipality = await Api.getMunicipality().catch(() => ({ name: 'Emergency Management' }));

  const needsByShelter = {};
  needs.forEach((n) => { (needsByShelter[n.shelter_id] || (needsByShelter[n.shelter_id] = [])).push(n); });
  const roadsBySegmentId = {};
  roads.forEach((r) => { roadsBySegmentId[r.road_segment_id] = r; });

  const criticalCount = needs.filter((n) => n.urgency.band === 'CRITICAL' || n.urgency.band === 'VERY_HIGH').length;
  const activeMissions = missions.filter((m) => m.status !== 'DELIVERED' && m.status !== 'CANCELLED');
  const availableVehicles = vehicles.filter((v) => v.status === 'AVAILABLE').length;

  const topNeed = needs[0]; // already sorted by urgency desc
  const warehouses = await Api.listResources();

  container.innerHTML = `
    <div class="flex-between mb-16">
      <div>
        <div class="eyebrow">Command Dashboard</div>
        <h1 class="section-heading">${escapeHtml(municipality.name)}</h1>
      </div>
      <button class="btn" id="refresh-btn">Refresh</button>
    </div>

    <div class="stat-row">
      <div class="stat-card"><div class="stat-value">${shelters.length}</div><div class="stat-label">Active shelters</div></div>
      <div class="stat-card"><div class="stat-value" style="color:${criticalCount ? 'var(--band-very-high)' : 'inherit'}">${criticalCount}</div><div class="stat-label">Critical / very high needs</div></div>
      <div class="stat-card"><div class="stat-value">${activeMissions.length}</div><div class="stat-label">Active missions</div></div>
      <div class="stat-card"><div class="stat-value">${availableVehicles} / ${vehicles.length}</div><div class="stat-label">Vehicles available</div></div>
    </div>

    <div class="grid" style="grid-template-columns: 1.3fr 1fr;">
      <div class="card">
        <div class="card-title">Operations Map</div>
        ${OpsMap.renderOpsMap()}
      </div>

      <div class="card">
        <div class="card-title">Priority Needs</div>
        <div id="priority-list">
          ${needs.slice(0, 6).map((n, i) => `
            <div class="list-item flex-between row-link priority-row" data-need="${n.need_id}">
              <div>
                <div style="font-weight:600;">${i + 1}. ${escapeHtml(n.shelter_name)}</div>
                <div class="small muted">${titleCase(n.resource_type)}</div>
              </div>
              ${bandBadge(n.urgency.band, n.urgency.score_display)}
            </div>
          `).join('')}
        </div>
      </div>
    </div>

    <div class="card mb-16" style="margin-top:16px;" id="recommendation-card">
      <div class="card-title">AI Recommendation — Top Priority Need</div>
      <div id="recommendation-content"><span class="spinner"></span> Running decision pipeline…</div>
    </div>

    <div class="card">
      <div class="card-title">Active Missions</div>
      ${activeMissions.length === 0 ? '<p class="muted small">No missions in flight.</p>' : `
      <table>
        <thead><tr><th>Vehicle</th><th>Resource</th><th>Destination</th><th>Status</th><th>ETA</th></tr></thead>
        <tbody>
          ${activeMissions.map((m) => `
            <tr>
              <td class="mono">${escapeHtml(m.vehicle_id)}</td>
              <td>${titleCase(m.resource_type)} · ${fmtQty(m.quantity_canonical, m.unit)}</td>
              <td>${escapeHtml(m.destination_shelter_id)}</td>
              <td>${titleCase(m.status)}</td>
              <td>${fmtMinutes(m.eta_minutes)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>`}
    </div>
  `;

  OpsMap.mountOpsMap(shelters, warehouses, needsByShelter, roadsBySegmentId);
  qs('refresh-btn').addEventListener('click', () => renderCoordinatorDashboard(params, container));
  document.querySelectorAll('.priority-row').forEach((row) => {
    row.addEventListener('click', () => { location.hash = `#/coordinator/needs/${row.dataset.need}`; });
  });

  if (topNeed) {
    try {
      const plan = await Api.recalculateNeed(topNeed.need_id);
      renderRecommendationSummary(plan, topNeed);
    } catch (err) {
      qs('recommendation-content').innerHTML = `<p class="muted small">Could not compute a recommendation: ${escapeHtml(err.message)}</p>`;
    }
  } else {
    qs('recommendation-content').innerHTML = `<p class="muted small">No active needs right now.</p>`;
  }
}

function renderRecommendationSummary(plan, need) {
  const box = qs('recommendation-content');
  if (!box) return;
  const rec = plan.recommendation;
  if (!rec || rec.no_acceptable_plan) {
    box.innerHTML = `<p style="color:var(--band-very-high);">No acceptable plan found for <strong>${escapeHtml(need.shelter_name)} · ${titleCase(need.resource_type)}</strong>. Escalate to human coordinator for manual sourcing.</p>`;
    return;
  }
  const topCandidate = plan.candidates.find((c) => c.candidate.candidate_id === rec.recommended_candidate_id);
  const cand = topCandidate.candidate;
  const util = topCandidate.utility;
  const feas = topCandidate.feasibility;
  box.innerHTML = `
    <div class="flex-between mb-12">
      <div>
        <div style="font-weight:700;font-size:16px;">${escapeHtml(need.shelter_name)} needs ${fmtQty(cand.quantity_canonical, need.unit)} ${titleCase(cand.resource_type)}</div>
        <div class="small muted">Source: ${escapeHtml(cand.source_name)} · Vehicle: ${escapeHtml(cand.vehicle_name)} · ETA ${fmtMinutes(cand.eta_minutes)}</div>
      </div>
      <div class="flex gap-8">
        ${qualityBadge(feas.band, feas.score_display, { unknownLabel: 'n/a' })}
        ${qualityBadge(util.band, util.score_display, { unknownLabel: 'n/a' })}
      </div>
    </div>
    <div class="flex gap-8 mb-12">
      <a href="#/coordinator/needs/${need.need_id}" class="btn btn-primary">View full reasoning &amp; approve</a>
    </div>
  `;
}

window.renderCoordinatorDashboard = renderCoordinatorDashboard;
