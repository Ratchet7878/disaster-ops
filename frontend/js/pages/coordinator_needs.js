// Active Needs list + the AI Recommendation screen (spec sections 156
// "Coordinator AI Recommendation Screen", 157 "Approval Workflow", 158
// "Modify Plan").

async function renderCoordinatorNeeds(params, container) {
  if (params.id) return renderNeedDetail(params.id, container);

  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  const needs = await Api.listNeeds();
  container.innerHTML = `
    <div class="eyebrow">Operations</div>
    <h1 class="section-heading mb-16">Active Needs</h1>
    <div class="card">
      <table>
        <thead><tr><th>Shelter</th><th>Resource</th><th>Target</th><th>Urgency</th><th>Recommendation</th><th></th></tr></thead>
        <tbody>
          ${needs.map((n) => `
            <tr class="row-link" data-need="${n.need_id}">
              <td>${escapeHtml(n.shelter_name)}</td>
              <td>${titleCase(n.resource_type)}</td>
              <td>${fmtQty(n.target_quantity_canonical, n.unit)}</td>
              <td>${bandBadge(n.urgency.band, n.urgency.score_display)}</td>
              <td class="small muted">${n.latest_recommendation_status ? titleCase(n.latest_recommendation_status) : '—'}</td>
              <td><a href="#/coordinator/needs/${n.need_id}" class="btn">Review</a></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
  document.querySelectorAll('tr.row-link').forEach((row) => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('a')) return;
      location.hash = `#/coordinator/needs/${row.dataset.need}`;
    });
  });
}

async function renderNeedDetail(needId, container) {
  container.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  let plan;
  try {
    plan = await Api.recalculateNeed(needId);
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Could not plan this need: ${escapeHtml(err.message)}</div>`;
    return;
  }
  const needs = await Api.listNeeds();
  const need = needs.find((n) => n.need_id === needId) || { need_id: needId, shelter_name: needId, resource_type: '', unit: '' };
  const urgency = plan.urgency;
  const rec = plan.recommendation;

  container.innerHTML = `
    <a href="#/coordinator/needs" class="small muted" style="text-decoration:none;">&larr; All needs</a>
    <div class="flex-between mb-16" style="margin-top:6px;">
      <div>
        <div class="eyebrow">${escapeHtml(need.shelter_name)}</div>
        <h1 class="section-heading">${titleCase(need.resource_type)} need</h1>
      </div>
      ${bandBadge(urgency.band, urgency.score_display)}
    </div>

    <div class="grid" style="grid-template-columns: 1fr 1fr 1fr 1fr 1fr; margin-bottom:16px;">
      ${renderUrgencyFactor('Time pressure', urgency.factors.time_pressure, 0.40)}
      ${renderUrgencyFactor('Severity', urgency.factors.resource_severity, 0.20)}
      ${renderUrgencyFactor('Vulnerability', urgency.factors.vulnerability, 0.15)}
      ${renderUrgencyFactor('Population', urgency.factors.population, 0.15)}
      ${renderUrgencyFactor('Local coping', urgency.factors.lack_of_local_coping, 0.10)}
    </div>
    <p class="small muted mb-16">
      Time to failure: <strong class="mono">${fmtMinutes(urgency.ttf_minutes)}</strong> ·
      Data confidence: <strong>${Math.round(urgency.data_confidence * 100)}%</strong>${urgency.provisional ? ' · <span style="color:var(--warn)">Provisional</span>' : ''}
    </p>

    ${renderRecommendationPanel(plan, need)}

    <div class="card">
      <div class="card-title">All Candidate Plans</div>
      ${renderCandidateTable(plan, need)}
    </div>
  `;

  wireApprovalButtons(needId, plan);
}

function renderUrgencyFactor(label, value, weight) {
  const pct = value === null || value === undefined ? null : Math.round(value * 100);
  return `
    <div class="stat-card">
      <div class="stat-value" style="font-size:20px;">${pct === null ? '—' : pct + '%'}</div>
      <div class="stat-label">${label} <span class="mono">(w=${weight})</span></div>
    </div>
  `;
}

function renderRecommendationPanel(plan, need) {
  const rec = plan.recommendation;
  if (!rec || rec.no_acceptable_plan) {
    return `
      <div class="card mb-16" style="border-color:var(--band-very-high);">
        <div class="card-title" style="color:var(--band-very-high);">No Acceptable Plan</div>
        <p>Every candidate is either infeasible or below the fallback threshold. This needs human escalation — check for available external resources or relax constraints manually.</p>
      </div>
    `;
  }
  const top = plan.candidates.find((c) => c.candidate.candidate_id === rec.recommended_candidate_id);
  const cand = top.candidate, feas = top.feasibility, util = top.utility, expl = rec.explanation;

  const whyLines = [
    [expl.full_coverage, 'Full need coverage'],
    [expl.arrives_before_failure, 'Arrives before predicted shortage'],
    [expl.downstream_risk === 'LOW', 'No donor shelter meaningfully endangered'],
    [expl.mission_disruption === 'NONE', 'No existing mission interrupted'],
    [expl.route_status === 'OPEN', 'Route currently open'],
    [expl.weather_risk === 'LOW', 'Weather risk low'],
  ];

  const alternatives = plan.candidates
    .filter((c) => rec.ranked_candidate_ids.includes(c.candidate.candidate_id) && c.candidate.candidate_id !== rec.recommended_candidate_id)
    .slice(0, 3);

  return `
    <div class="card mb-16">
      <div class="flex-between mb-12">
        <div class="card-title" style="margin-bottom:0;">Recommended Plan</div>
        <span class="small muted mono">expires ${fmtTime(rec.expires_at)}</span>
      </div>
      <div class="flex gap-16 mb-16" style="flex-wrap:wrap;">
        <div><div class="eyebrow">Source</div><strong>${escapeHtml(cand.source_name)}</strong></div>
        <div><div class="eyebrow">Vehicle</div><strong>${escapeHtml(cand.vehicle_name)}</strong></div>
        <div><div class="eyebrow">Quantity</div><strong>${fmtQty(cand.quantity_canonical, need.unit)}</strong></div>
        <div><div class="eyebrow">ETA</div><strong>${fmtMinutes(cand.eta_minutes)}</strong></div>
        <div><div class="eyebrow">Pattern</div><strong>${titleCase(cand.generation_pattern)}</strong></div>
      </div>
      <div class="flex gap-16 mb-16">
        <div><div class="eyebrow">Feasibility</div>${qualityBadge(feas.band, feas.score_display)}</div>
        <div><div class="eyebrow">Utility</div>${qualityBadge(util.band, util.score_display)}</div>
      </div>
      <div class="divider"></div>
      <div class="mb-16">
        <div class="eyebrow mb-8">Why this plan?</div>
        ${whyLines.map(([ok, text]) => `<div class="small" style="margin-bottom:4px;color:${ok ? 'var(--ok)' : 'var(--ink-400)'}">${ok ? '✓' : '·'} ${text}</div>`).join('')}
      </div>
      ${alternatives.length ? `
      <div class="mb-16">
        <div class="eyebrow mb-8">Alternatives considered</div>
        ${alternatives.map((a) => `<div class="small muted mb-4">${escapeHtml(a.candidate.source_name)} / ${escapeHtml(a.candidate.vehicle_name)} — utility ${a.utility.score_display}</div>`).join('')}
      </div>` : ''}
      <div class="flex gap-8">
        <button class="btn btn-primary" id="approve-btn">Approve</button>
        <button class="btn" id="select-alt-btn">Select alternative</button>
        <button class="btn btn-danger" id="reject-btn">Reject</button>
      </div>
      <div id="approval-result" class="small" style="margin-top:10px;"></div>
    </div>
  `;
}

function renderCandidateTable(plan, need) {
  const rows = plan.candidates.map((c) => {
    const cand = c.candidate, feas = c.feasibility, util = c.utility;
    const isRecommended = plan.recommendation && cand.candidate_id === plan.recommendation.recommended_candidate_id;
    return `
      <tr style="${isRecommended ? 'background:rgba(232,112,58,0.08);' : ''}">
        <td>${titleCase(cand.generation_pattern)}${isRecommended ? ' <span class="mono small" style="color:var(--accent);">★</span>' : ''}</td>
        <td>${escapeHtml(cand.source_name)}</td>
        <td>${escapeHtml(cand.vehicle_name)}</td>
        <td>${fmtQty(cand.quantity_canonical, need.unit)}${cand.is_partial ? ` <span class="small" style="color:var(--warn);">(${Math.round(cand.fulfillment_fraction * 100)}%)</span>` : ''}</td>
        <td>${fmtMinutes(cand.eta_minutes)}</td>
        <td>${feasibilityStatusLabel(feas)}</td>
        <td>${util ? qualityBadge(util.band, util.score_display, { unknownLabel: 'n/a' }) : '<span class="muted small">—</span>'}</td>
      </tr>
    `;
  }).join('');
  return `
    <table>
      <thead><tr><th>Pattern</th><th>Source</th><th>Vehicle</th><th>Qty</th><th>ETA</th><th>Feasibility</th><th>Utility</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function wireApprovalButtons(needId, plan) {
  const rec = plan.recommendation;
  if (!rec || rec.no_acceptable_plan) return;

  const resultBox = () => qs('approval-result');

  qs('approve-btn')?.addEventListener('click', async () => {
    try {
      const resp = await Api.approveRecommendation(rec.recommendation_id, {});
      resultBox().innerHTML = `<span style="color:var(--ok);">Approved. Mission ${escapeHtml(resp.mission_id)} dispatched.</span>`;
      toast('Mission dispatched', 'success');
      setTimeout(() => { location.hash = '#/coordinator/missions'; }, 900);
    } catch (err) {
      resultBox().innerHTML = `<span style="color:var(--danger);">${escapeHtml(err.message)}</span>`;
      toast(err.message, 'error');
    }
  });

  qs('reject-btn')?.addEventListener('click', async () => {
    const reason = prompt('Reason for rejecting this recommendation?');
    if (reason === null) return;
    try {
      await Api.rejectRecommendation(rec.recommendation_id, { reason });
      toast('Rejected — replanning', 'success');
      renderNeedDetail(needId, qs('coord-content'));
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  qs('select-alt-btn')?.addEventListener('click', async () => {
    const alternatives = plan.candidates.filter((c) => rec.ranked_candidate_ids.includes(c.candidate.candidate_id));
    const choice = prompt(
      'Enter the number of the alternative to approve:\n' +
      alternatives.map((a, i) => `${i + 1}. ${a.candidate.source_name} / ${a.candidate.vehicle_name} (utility ${a.utility.score_display})`).join('\n')
    );
    const idx = parseInt(choice, 10) - 1;
    if (isNaN(idx) || !alternatives[idx]) return;
    try {
      const resp = await Api.modifyRecommendation(rec.recommendation_id, { candidate_id: alternatives[idx].candidate.candidate_id });
      resultBox().innerHTML = `<span style="color:var(--ok);">Approved alternative. Mission ${escapeHtml(resp.mission_id)} dispatched.</span>`;
      toast('Alternative approved', 'success');
      setTimeout(() => { location.hash = '#/coordinator/missions'; }, 900);
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

window.renderCoordinatorNeeds = renderCoordinatorNeeds;
