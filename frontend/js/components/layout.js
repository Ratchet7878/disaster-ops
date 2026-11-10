// Shared page shells (spec section 150 vs 154: two deliberately different
// interfaces over one shared backend).

const COORD_NAV = [
  { section: 'Operations', items: [
    { path: '/coordinator/dashboard', label: 'Command Dashboard' },
    { path: '/coordinator/agent', label: 'AI Agent' },
    { path: '/coordinator/needs', label: 'Active Needs' },
    { path: '/coordinator/shelters', label: 'Shelters' },
    { path: '/coordinator/missions', label: 'Missions' },
  ]},
  { section: 'Resources', items: [
    { path: '/coordinator/vehicles', label: 'Vehicles' },
    { path: '/coordinator/resources', label: 'Warehouses' },
    { path: '/coordinator/roads', label: 'Roads & Weather' },
  ]},
  { section: 'System', items: [
    { path: '/coordinator/audit', label: 'Audit Log' },
  ]},
];

function coordinatorShell(user, activePath) {
  const navHtml = COORD_NAV.map((group) => `
    <div class="section-label">${group.section}</div>
    ${group.items.map((it) => `<a href="#${it.path}" class="${activePath === it.path ? 'active' : ''}">${it.label}</a>`).join('')}
  `).join('');

  return `
    <div class="topbar">
      <div class="brand"><span class="brand-mark">◈</span> DisasterOps</div>
      <div class="topbar-right">
        <span class="pill">${escapeHtml(user.name)} · COORDINATOR</span>
        <a href="#/login" id="logout-link" class="logout-link">Log out</a>
      </div>
    </div>
    <div class="shell">
      <nav class="sidenav">${navHtml}</nav>
      <main class="shell-main" id="coord-content"></main>
    </div>
    <div class="toast-region" id="toast-region"></div>
  `;
}

function volunteerShell(user) {
  return `
    <div class="v-shell">
      <div class="v-topbar">
        <div class="flex-between">
          <div class="brand"><span class="brand-mark">◈</span> DisasterOps</div>
          <a href="#/login" id="logout-link" class="logout-link" style="color:#fff;border-color:rgba(255,255,255,0.25)">Log out</a>
        </div>
      </div>
      <div class="v-main" id="v-content"></div>
    </div>
    <div class="toast-region" id="toast-region"></div>
  `;
}

function wireLogout() {
  const link = qs('logout-link');
  if (link) {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      AuthStore.setToken(null);
      AuthStore.setUser(null);
      location.hash = '#/login';
    });
  }
}

window.Layout = { coordinatorShell, volunteerShell, wireLogout };
