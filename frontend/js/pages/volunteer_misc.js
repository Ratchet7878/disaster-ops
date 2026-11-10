// Critical Update (spec 151.1), Supply Request (spec 152), and
// Deliveries (spec 153) screens.

const CRITICAL_CATEGORIES = [
  'RESOURCE_SHORTAGE', 'ROAD_BLOCKED', 'POWER_FAILURE', 'SHELTER_ACCESS_PROBLEM', 'RAPID_POPULATION_INCREASE', 'OTHER',
];

async function renderVolunteerCritical(params, container) {
  let selected = null;
  container.innerHTML = `
    <div class="v-label">Critical Update</div>
    <h2 class="mb-16">What changed?</h2>
    <div class="v-choice-grid" id="category-grid">
      ${CRITICAL_CATEGORIES.map((c) => `<div class="v-choice" data-cat="${c}">${titleCase(c)}</div>`).join('')}
    </div>
    <div class="v-card">
      <div class="field">
        <label>Describe</label>
        <textarea id="f-desc" rows="3" placeholder="What's happening?"></textarea>
      </div>
    </div>
    <button class="v-btn critical" id="send-critical-btn">Send critical update</button>
  `;

  document.querySelectorAll('#category-grid .v-choice').forEach((el) => {
    el.addEventListener('click', () => {
      document.querySelectorAll('#category-grid .v-choice').forEach((c) => c.classList.remove('selected'));
      el.classList.add('selected');
      selected = el.dataset.cat;
    });
  });

  qs('send-critical-btn').addEventListener('click', async () => {
    if (!selected) { toast('Choose what changed first', 'error'); return; }
    const shelters = await Api.listShelters();
    const shelter = shelters[0];
    try {
      await Api.submitCriticalUpdate(shelter.shelter_id, {
        category: selected,
        description: qs('f-desc').value,
        source: 'REGISTERED_VOLUNTEER',
      });
      toast('Critical update sent', 'success');
      location.hash = '#/volunteer/dashboard';
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

async function renderVolunteerRequest(params, container) {
  const shelters = await Api.listShelters();
  const shelter = shelters[0];
  const types = shelter.resources.map((r) => r.resource_type);

  container.innerHTML = `
    <div class="v-label">Request Supplies</div>
    <h2 class="mb-16">${escapeHtml(shelter.name)}</h2>
    <form id="request-form">
      <div class="v-card">
        <div class="field">
          <label>Resource</label>
          <select id="f-resource">${types.map((t) => `<option value="${t}">${titleCase(t)}</option>`).join('')}</select>
        </div>
        <div class="field"><label>Quantity requested</label><input type="number" step="any" id="f-qty" required /></div>
        <div class="field"><label>Reason</label><input type="text" id="f-reason" placeholder="Why do you need this?" /></div>
      </div>
      <div class="v-card">
        <div class="v-label">Your perceived urgency</div>
        <div class="v-choice-grid" id="urgency-grid">
          ${['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((u) => `<div class="v-choice" data-u="${u}">${titleCase(u)}</div>`).join('')}
        </div>
        <p class="hint" style="color:#6b6252;">This is an extra signal for the coordinator — DisasterOps calculates the actual urgency score from shelter data, not from this choice alone.</p>
      </div>
      <button type="submit" class="v-btn" id="submit-request-btn">Submit request</button>
    </form>
  `;

  let humanUrgency = null;
  document.querySelectorAll('#urgency-grid .v-choice').forEach((el) => {
    el.addEventListener('click', () => {
      document.querySelectorAll('#urgency-grid .v-choice').forEach((c) => c.classList.remove('selected'));
      el.classList.add('selected');
      humanUrgency = el.dataset.u;
    });
  });

  qs('request-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const type = qs('f-resource').value;
    const resRow = shelter.resources.find((r) => r.resource_type === type);
    const rawQty = parseFloat(qs('f-qty').value);
    const qty = resRow.unit === 'MILLILITRE' ? rawQty * 1000 : rawQty;
    try {
      await Api.submitRequest(shelter.shelter_id, {
        resource_type: type,
        quantity_requested_canonical: qty,
        reason: qs('f-reason').value,
        human_perceived_urgency: humanUrgency,
      });
      toast('Request submitted', 'success');
      location.hash = '#/volunteer/dashboard';
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

async function renderVolunteerDeliveries(params, container) {
  const shelters = await Api.listShelters();
  const shelter = shelters[0];
  const missions = (await Api.listMissions()).filter((m) => m.destination_shelter_id === shelter.shelter_id);

  container.innerHTML = `
    <div class="v-label">Deliveries</div>
    <h2 class="mb-16">${escapeHtml(shelter.name)}</h2>
    ${missions.length === 0 ? '<p class="small" style="color:#6b6252;">No deliveries yet.</p>' : missions.map((m) => `
      <div class="v-card">
        <div class="flex-between mb-8">
          <div style="font-weight:700;">${titleCase(m.resource_type)}</div>
          <span class="band-badge" style="background:#eee;color:#333;">${titleCase(m.status)}</span>
        </div>
        <div class="small" style="color:#6b6252;">Quantity: ${fmtQty(m.quantity_canonical, m.unit)}</div>
        <div class="small" style="color:#6b6252;">Vehicle: ${escapeHtml(m.vehicle_id)}</div>
        ${m.status !== 'DELIVERED' ? `<div class="small" style="color:#6b6252;margin-bottom:10px;">ETA: ${fmtMinutes(m.eta_minutes)}</div>
          <button class="v-btn secondary confirm-btn" data-mission="${m.mission_id}" data-qty="${m.quantity_canonical}">Confirm delivery</button>`
          : `<div class="small" style="color:#6b6252;">Received: ${fmtQty(m.actual_quantity_received, m.unit)}</div>`}
      </div>
    `).join('')}
  `;

  document.querySelectorAll('.confirm-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await Api.updateMissionStatus(btn.dataset.mission, {
          status: 'DELIVERED', actual_quantity_received: parseFloat(btn.dataset.qty), damaged_or_missing: 0,
        });
        toast('Delivery confirmed', 'success');
        renderVolunteerDeliveries(params, container);
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  });
}

window.renderVolunteerCritical = renderVolunteerCritical;
window.renderVolunteerRequest = renderVolunteerRequest;
window.renderVolunteerDeliveries = renderVolunteerDeliveries;
