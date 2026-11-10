// Volunteer home screen (spec section 150.1): simple, fast, low
// cognitive load. A volunteer should never need to understand utility
// ranking or candidate generation.

async function renderVolunteerDashboard(params, container) {
  const user = AuthStore.getUser();
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

  let shelter, needs, missions;
  try {
    const shelters = await Api.listShelters();
    shelter = shelters[0];
    const allNeeds = await Api.listNeeds();
    needs = allNeeds.filter((n) => n.shelter_id === shelter.shelter_id);
    const allMissions = await Api.listMissions();
    missions = allMissions.filter((m) => m.destination_shelter_id === shelter.shelter_id && m.status !== 'DELIVERED');
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Could not load shelter data: ${escapeHtml(err.message)}</div>`;
    return;
  }

  container.innerHTML = `
    <div class="v-card">
      <div class="v-label">${escapeHtml(shelter.name)}</div>
      <div class="flex-between mb-8">
        <div>
          <div style="font-size:22px;font-weight:700;">${shelter.population_total} people</div>
          <div class="small" style="color:#6b6252;">Last update ${timeAgo(shelter.last_report_at)}</div>
        </div>
      </div>
    </div>

    <a href="#/volunteer/report" class="v-btn">Update hourly status</a>
    <a href="#/volunteer/critical-update" class="v-btn critical">Send critical update</a>
    <a href="#/volunteer/request" class="v-btn secondary">Request supplies</a>

    <div class="v-card">
      <div class="v-label">Active requests</div>
      ${needs.length === 0 ? '<p class="small" style="color:#6b6252;">No active requests right now.</p>' : needs.map((n) => `
        <div class="list-item" style="border-color:#e4e0d6;">
          <div class="flex-between">
            <div>
              <div style="font-weight:600;">${titleCase(n.resource_type)}</div>
              <div class="small" style="color:#6b6252;">${n.latest_recommendation_status ? titleCase(n.latest_recommendation_status) : 'Awaiting review'}</div>
            </div>
            ${bandBadge(n.urgency.band, n.urgency.score_display)}
          </div>
        </div>
      `).join('')}
    </div>

    <div class="v-card">
      <div class="v-label">Incoming deliveries</div>
      ${missions.length === 0 ? '<p class="small" style="color:#6b6252;">Nothing en route yet.</p>' : missions.map((m) => `
        <div class="list-item" style="border-color:#e4e0d6;">
          <div class="flex-between">
            <div>
              <div style="font-weight:600;">${titleCase(m.resource_type)} · ${fmtQty(m.quantity_canonical, m.unit)}</div>
              <div class="small" style="color:#6b6252;">${titleCase(m.status)}${m.status !== 'DELIVERED' ? ' · ETA ' + fmtMinutes(m.eta_minutes) : ''}</div>
            </div>
            ${m.status !== 'DELIVERED' ? `<button class="btn confirm-delivery-btn" data-mission="${m.mission_id}">Confirm arrival</button>` : ''}
          </div>
        </div>
      `).join('')}
    </div>
  `;

  document.querySelectorAll('.confirm-delivery-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const missionId = btn.dataset.mission;
      const mission = missions.find((m) => m.mission_id === missionId);
      btn.disabled = true;
      try {
        await Api.updateMissionStatus(missionId, {
          status: 'DELIVERED',
          actual_quantity_received: mission.quantity_canonical,
          damaged_or_missing: 0,
        });
        toast('Delivery confirmed', 'success');
        renderVolunteerDashboard(params, container);
      } catch (err) {
        toast(err.message, 'error');
        btn.disabled = false;
      }
    });
  });
}

window.renderVolunteerDashboard = renderVolunteerDashboard;
