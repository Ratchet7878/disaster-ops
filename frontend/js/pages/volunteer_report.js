// Hourly status form (spec section 151): auto-loads previous values so
// the volunteer only has to correct what changed.

async function renderVolunteerReport(params, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const shelters = await Api.listShelters();
  const shelter = shelters[0];
  const resources = shelter.resources;
  const byType = {};
  resources.forEach((r) => { byType[r.resource_type] = r; });

  const trackedTypes = ['WATER', 'FOOD', 'BLANKET', 'BATTERY'];

  container.innerHTML = `
    <div class="v-label">Hourly Status Report</div>
    <h2 class="mb-16">${escapeHtml(shelter.name)}</h2>
    <form id="report-form">
      <div class="v-card">
        <div class="v-label">Population</div>
        <div class="field"><label>Current evacuees</label><input type="number" id="f-pop" value="${shelter.population_total}" required /></div>
        <div class="field-row">
          <div class="field"><label>New arrivals</label><input type="number" id="f-arrivals" value="0" /></div>
          <div class="field"><label>Departures</label><input type="number" id="f-departures" value="0" /></div>
        </div>
      </div>

      ${trackedTypes.map((type) => {
        const r = byType[type];
        if (!r) return '';
        return `
        <div class="v-card">
          <div class="v-label">${titleCase(type)}</div>
          <div class="field">
            <label>Current quantity (${r.unit === 'MILLILITRE' ? 'litres' : r.unit.toLowerCase()})</label>
            <input type="number" step="any" id="f-${type}" value="${r.unit === 'MILLILITRE' ? (r.quantity_canonical / 1000) : r.quantity_canonical}" required />
            <div class="hint">Previous: ${fmtQty(r.quantity_canonical, r.unit)}</div>
          </div>
        </div>`;
      }).join('')}

      <div class="v-card">
        <div class="v-label">Road access</div>
        <div class="field">
          <label>Primary road</label>
          <select id="f-road-primary">
            <option value="OPEN" ${shelter.road_access.primary_segment_id ? '' : ''} selected>Open</option>
            <option value="RESTRICTED">Restricted</option>
            <option value="BLOCKED">Blocked</option>
            <option value="UNKNOWN">Unknown</option>
          </select>
        </div>
      </div>

      <button type="submit" class="v-btn" id="submit-report-btn">Submit report</button>
    </form>
  `;

  qs('report-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = qs('submit-report-btn');
    btn.textContent = 'Submitting…';
    const resourcesPayload = trackedTypes.filter((t) => byType[t]).map((type) => {
      const r = byType[type];
      const rawVal = parseFloat(qs(`f-${type}`).value);
      const qty = r.unit === 'MILLILITRE' ? rawVal * 1000 : rawVal;
      return { type, quantity_canonical: qty, unit: r.unit, measurement: 'ESTIMATED' };
    });
    try {
      await Api.submitReport(shelter.shelter_id, {
        occurred_at: new Date().toISOString(),
        population: {
          total: parseInt(qs('f-pop').value, 10),
          new_arrivals: parseInt(qs('f-arrivals').value || '0', 10),
          departures: parseInt(qs('f-departures').value || '0', 10),
        },
        resources: resourcesPayload,
        road_access: { primary: qs('f-road-primary').value },
        source: 'REGISTERED_VOLUNTEER',
      });
      toast('Report submitted', 'success');
      location.hash = '#/volunteer/dashboard';
    } catch (err) {
      toast(err.message, 'error');
      btn.textContent = 'Submit report';
    }
  });
}

window.renderVolunteerReport = renderVolunteerReport;
