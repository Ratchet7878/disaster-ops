// Operations map: a real interactive map (Leaflet + OpenStreetMap tiles --
// free, no API key). Shelters are circles coloured by worst urgency band; the
// ring colour is the primary road status. Warehouses are green squares.
// Layer switcher: OpenStreetMap, GSI Japan standard map, plus an optional GSI
// flood-hazard overlay. Google Maps would work the same way but needs a paid
// API key; swap the tile layers below if you want it later.

const ROAD_COLOR = { OPEN: '#147e52', RESTRICTED: '#b8791f', UNKNOWN: '#8a9690', BLOCKED: '#b0202f' };
const BAND_COLOR = { LOW: '#147e52', MODERATE: '#b8791f', HIGH: '#c9642c', VERY_HIGH: '#c14a29', CRITICAL: '#b0202f' };
const BAND_ORDER = ['LOW', 'MODERATE', 'HIGH', 'VERY_HIGH', 'CRITICAL'];

let _opsMapInstance = null;

function renderOpsMap() {
  return `
    <div id="ops-map" style="width:100%;height:380px;border-radius:8px;border:1px solid #dbe6e1;z-index:0;"></div>
    <div class="flex gap-16 small muted" style="margin-top:8px;flex-wrap:wrap;">
      <span><span style="display:inline-block;width:8px;height:8px;background:#147e52;margin-right:4px;"></span>Warehouse</span>
      <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#b0202f;margin-right:4px;"></span>Critical need</span>
      <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#147e52;margin-right:4px;"></span>Stable</span>
      <span>Ring color = primary road status</span>
    </div>`;
}

// Call after the HTML from renderOpsMap() is in the DOM.
function mountOpsMap(shelters, warehouses, needsByShelter, roadsBySegmentId) {
  const el = document.getElementById('ops-map');
  if (!el) return;
  if (_opsMapInstance) { _opsMapInstance.remove(); _opsMapInstance = null; }
  if (!window.L) {
    el.innerHTML = '<div class="empty-state small">Map library could not load (needs internet access).</div>';
    return;
  }

  const map = L.map(el, { scrollWheelZoom: false });
  _opsMapInstance = map;

  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
  const gsi = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html">GSI Japan</a>',
  });
  const flood = L.tileLayer('https://disaportaldata.gsi.go.jp/raster/01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png', {
    maxNativeZoom: 17, maxZoom: 19, opacity: 0.6,
    attribution: '<a href="https://disaportal.gsi.go.jp/">Hazard map portal (GSI/MLIT)</a>',
  });
  L.control.layers({ OpenStreetMap: osm, 'GSI Japan map': gsi }, { 'Flood hazard overlay': flood }).addTo(map);

  const bounds = [];
  warehouses.forEach((w) => {
    if (w.latitude == null || w.longitude == null) return;
    const pos = [w.latitude, w.longitude];
    bounds.push(pos);
    L.marker(pos, {
      icon: L.divIcon({
        className: '',
        html: '<div style="width:16px;height:16px;background:#147e52;border:2px solid #143e31;box-shadow:0 0 0 2px #fff;"></div>',
        iconSize: [16, 16], iconAnchor: [8, 8],
      }),
    }).addTo(map).bindTooltip(`Warehouse: ${escapeHtml(w.name)}`);
  });

  shelters.forEach((s) => {
    if (s.latitude == null || s.longitude == null) return;
    const pos = [s.latitude, s.longitude];
    bounds.push(pos);
    const needs = needsByShelter[s.shelter_id] || [];
    const worst = needs.reduce((acc, n) => {
      const b = n.urgency && n.urgency.band;
      if (!b) return acc;
      return !acc || BAND_ORDER.indexOf(b) > BAND_ORDER.indexOf(acc) ? b : acc;
    }, null);
    const roadId = s.road_access ? s.road_access.primary_segment_id : null;
    const road = roadId && roadsBySegmentId[roadId] ? roadsBySegmentId[roadId] : null;
    const m = L.circleMarker(pos, {
      radius: 11, weight: 5, color: road ? ROAD_COLOR[road.status] : '#8a9690',
      fillColor: worst ? BAND_COLOR[worst] : '#5c6863', fillOpacity: 1,
      dashArray: road && road.status === 'BLOCKED' ? '3 3' : null,
    }).addTo(map);
    m.bindTooltip(
      `<b>${escapeHtml(s.name)}</b><br>${worst ? 'Worst need: ' + titleCase(worst) : 'No active needs'}` +
      `<br>Road: ${road ? titleCase(road.status) : 'unknown'}`
    );
    m.on('click', () => { location.hash = `#/coordinator/shelters/${s.shelter_id}`; });
  });

  if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
  else map.setView([35.68, 139.76], 5);
  // layout may still be settling when mounted
  setTimeout(() => map.invalidateSize(), 0);
}

window.OpsMap = { renderOpsMap, mountOpsMap };
