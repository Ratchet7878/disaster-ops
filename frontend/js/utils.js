// Shared formatting helpers used across pages.

function fmtQty(qty, unit) {
  if (qty === null || qty === undefined) return '—';
  const units = {
    MILLILITRE: () => (qty >= 1000 ? `${(qty / 1000).toFixed(qty % 1000 === 0 ? 0 : 1)} L` : `${Math.round(qty)} mL`),
    PORTION: () => `${Math.round(qty)} portions`,
    ITEM: () => `${Math.round(qty)} items`,
    UNIT: () => `${Math.round(qty)} units`,
    HOUR_EQUIVALENT: () => `${qty.toFixed(1)} h`,
    CARGO_LITRE: () => `${Math.round(qty)} L cargo`,
  };
  return (units[unit] || (() => `${Math.round(qty)} ${unit || ''}`))();
}

function fmtMinutes(min) {
  if (min === null || min === undefined) return '—';
  if (min === Infinity) return 'no limit';
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function timeAgo(iso) {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.round(ms / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  return `${h}h ${min % 60}m ago`;
}

function bandBadge(band, scoreDisplay, opts) {
  opts = opts || {};
  if (!band) return `<span class="band-badge muted"><span class="dot" style="background:#666"></span>${opts.unknownLabel || 'Unknown'}</span>`;
  const label = band.replace(/_/g, ' ');
  const score = scoreDisplay !== undefined && scoreDisplay !== null ? ` ${scoreDisplay}/10` : '';
  return `<span class="band-badge band-${band}"><span class="dot"></span>${label}${score}</span>`;
}

// Feasibility/Utility scores run the OPPOSITE semantic direction from
// urgency: a high urgency score is alarming (red), but a high
// feasibility or utility score is good news (green). Reusing
// bandBadge's color ramp for these would show a great plan in the same
// red/orange used to flag a shelter in crisis, so they get their own
// quality-scale mapping instead.
const QUALITY_RANK = {
  VERY_LOW: 0, VERY_POOR: 0, POOR: 1, LOW: 1,
  MODERATE: 2, ACCEPTABLE: 2,
  HIGH: 3, GOOD: 3,
  VERY_HIGH: 4, VERY_GOOD: 4, EXCELLENT: 4,
};
const QUALITY_COLORS = ['#c22b3a', '#d3552f', '#c99a3e', '#5b8a72', '#3f9d6e'];

function qualityBadge(band, scoreDisplay, opts) {
  opts = opts || {};
  if (!band) return `<span class="band-badge muted"><span class="dot" style="background:#666"></span>${opts.unknownLabel || 'Unknown'}</span>`;
  const rank = QUALITY_RANK[band] !== undefined ? QUALITY_RANK[band] : 2;
  const color = QUALITY_COLORS[rank];
  const label = band.replace(/_/g, ' ');
  const score = scoreDisplay !== undefined && scoreDisplay !== null ? ` ${scoreDisplay}/10` : '';
  return `<span class="band-badge" style="background:${color}26;color:${color};"><span class="dot" style="background:${color};"></span>${label}${score}</span>`;
}

function feasibilityStatusLabel(feas) {
  if (!feas) return '<span class="muted small">not evaluated</span>';
  if (feas.status === 'SCOREABLE') return qualityBadge(feas.band, feas.score_display);
  const labels = {
    HARD_INFEASIBLE: 'Not feasible',
    NEEDS_DATA: 'Needs data',
    INVALID_INPUT: 'Invalid input',
  };
  return `<span class="band-badge muted">${labels[feas.status] || feas.status}</span>`;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function titleCase(s) {
  if (!s) return '';
  return s.toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function qs(id) { return document.getElementById(id); }

function toast(message, kind) {
  const region = qs('toast-region');
  if (!region) return;
  const el = document.createElement('div');
  el.className = 'toast' + (kind ? ' ' + kind : '');
  el.textContent = message;
  region.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

window.Fmt = { fmtQty, fmtMinutes, fmtTime, fmtDateTime, timeAgo, bandBadge, qualityBadge, feasibilityStatusLabel, escapeHtml, titleCase };
window.qs = qs;
window.toast = toast;
