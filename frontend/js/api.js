// DisasterOps frontend — API client.
// Talks to the Flask backend (spec section 164's REST API map). Change
// API_BASE if the backend runs somewhere other than localhost:5001.
const API_BASE = window.DISASTEROPS_API_BASE || 'http://localhost:5001/api';

function getToken() {
  return localStorage.getItem('disasterops_token');
}
function setToken(token) {
  if (token) localStorage.setItem('disasterops_token', token);
  else localStorage.removeItem('disasterops_token');
}
function getUser() {
  const raw = localStorage.getItem('disasterops_user');
  return raw ? JSON.parse(raw) : null;
}
function setUser(user) {
  if (user) localStorage.setItem('disasterops_user', JSON.stringify(user));
  else localStorage.removeItem('disasterops_user');
}

class ApiError extends Error {
  constructor(status, body) {
    super((body && (body.message || body.error)) || `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (method !== 'GET') headers['Idempotency-Key'] = cryptoRandomId();

  let resp;
  try {
    resp = await fetch(API_BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    throw new ApiError(0, { error: 'NETWORK_ERROR', message: 'Cannot reach the DisasterOps backend at ' + API_BASE + '. Is it running?' });
  }

  let data = null;
  const text = await resp.text();
  if (text) {
    try { data = JSON.parse(text); } catch (_e) { data = { raw: text }; }
  }
  if (resp.status === 401) {
    setToken(null); setUser(null);
    if (location.hash !== '#/login') location.hash = '#/login';
  }
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data;
}

function cryptoRandomId() {
  if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
  return 'idem_' + Math.random().toString(36).slice(2) + Date.now();
}

const Api = {
  login: (email, password) => request('POST', '/auth/login', { email, password }),
  me: () => request('GET', '/me'),
  demoUsers: () => request('GET', '/demo-users'),
  getMunicipality: () => request('GET', '/municipality'),

  listShelters: () => request('GET', '/shelters'),
  getShelter: (id) => request('GET', `/shelters/${id}`),
  submitReport: (shelterId, body) => request('POST', `/shelters/${shelterId}/reports`, body),
  submitCriticalUpdate: (shelterId, body) => request('POST', `/shelters/${shelterId}/critical-updates`, body),
  submitRequest: (shelterId, body) => request('POST', `/shelters/${shelterId}/requests`, body),

  listNeeds: () => request('GET', '/needs'),
  getNeed: (id) => request('GET', `/needs/${id}`),
  recalculateNeed: (id) => request('POST', `/needs/${id}/recalculate`),

  getRecommendationForNeed: (needId) => request('GET', `/recommendations/need/${needId}`),
  approveRecommendation: (id, body) => request('POST', `/recommendations/${id}/approve`, body || {}),
  rejectRecommendation: (id, body) => request('POST', `/recommendations/${id}/reject`, body || {}),
  modifyRecommendation: (id, body) => request('POST', `/recommendations/${id}/modify`, body || {}),

  listMissions: () => request('GET', '/missions'),
  getMission: (id) => request('GET', `/missions/${id}`),
  updateMissionStatus: (id, body) => request('POST', `/missions/${id}/status`, body),

  listVehicles: () => request('GET', '/vehicles'),
  listResources: () => request('GET', '/resources'),
  listRoads: () => request('GET', '/roads'),
  createRoadEvent: (body) => request('POST', '/roads/events', body),
  getWeather: () => request('GET', '/weather'),
  getAudit: () => request('GET', '/audit'),
  health: () => request('GET', '/health'),
};

window.Api = Api;
window.AuthStore = { getToken, setToken, getUser, setUser };
window.ApiError = ApiError;
