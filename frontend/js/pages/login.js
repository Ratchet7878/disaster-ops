// Login page (spec section 148). Offers one-click demo accounts so
// judges don't have to type passwords during a live demo, alongside a
// normal email/password form.

async function renderLogin(params, container) {
  container.className = '';
  document.body.className = '';
  container.innerHTML = `
    <div style="min-height:100vh; display:flex; align-items:center; justify-content:center; background:radial-gradient(circle at 20% 20%, #1c4d3c, #143e31 60%);">
      <div style="width:100%; max-width:400px; padding:20px;">
        <div class="flex gap-8 mb-24" style="justify-content:center;">
          <span class="brand-mark" style="width:36px;height:36px;font-size:18px;">◈</span>
          <h1 style="font-size:28px; color:#ffffff;">DisasterOps</h1>
        </div>
        <div class="card mb-16">
          <div class="card-title">Sign in</div>
          <form id="login-form">
            <div class="field">
              <label>Email</label>
              <input type="email" id="login-email" placeholder="coordinator@disasterops.local" required />
            </div>
            <div class="field">
              <label>Password</label>
              <input type="password" id="login-password" placeholder="demo1234" required />
            </div>
            <div id="login-error" class="small" style="color:#ff9aa4; margin-bottom: 10px; display:none;"></div>
            <button type="submit" class="btn btn-primary btn-block btn-lg">
              <span id="login-btn-label">Sign in</span>
            </button>
          </form>
        </div>
        <div class="card">
          <div class="card-title">Demo accounts</div>
          <p class="small muted mb-12">Every account uses the password <span class="mono">demo1234</span>. Pick one to jump straight in.</p>
          <div id="demo-user-list" class="small muted">Loading…</div>
        </div>
      </div>
    </div>
  `;

  const form = qs('login-form');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await doLogin(qs('login-email').value, qs('login-password').value);
  });

  try {
    const users = await Api.demoUsers();
    const grouped = { COORDINATOR: [], ADMIN: [], VOLUNTEER: [] };
    users.forEach((u) => { (grouped[u.role] || (grouped[u.role] = [])).push(u); });
    const roleLabel = { COORDINATOR: 'Coordinator', ADMIN: 'Admin', VOLUNTEER: 'Shelter volunteer' };
    qs('demo-user-list').innerHTML = Object.entries(grouped).filter(([, list]) => list.length).map(([role, list]) => `
      <div class="mb-12">
        <div class="eyebrow">${roleLabel[role] || role}</div>
        ${list.map((u) => `
          <button class="btn btn-ghost btn-block demo-user-btn" style="justify-content:flex-start;margin-bottom:4px;" data-email="${escapeHtml(u.email)}">
            ${escapeHtml(u.name)} <span class="muted mono" style="margin-left:auto;font-size:11px;">${escapeHtml(u.assigned_shelter_id || '')}</span>
          </button>
        `).join('')}
      </div>
    `).join('');
    document.querySelectorAll('.demo-user-btn').forEach((btn) => {
      btn.addEventListener('click', () => doLogin(btn.dataset.email, 'demo1234'));
    });
  } catch (err) {
    qs('demo-user-list').innerHTML = `<span style="color:#ff9aa4;">Could not reach backend at ${escapeHtml(API_BASE)}. Is it running?</span>`;
  }
}

async function doLogin(email, password) {
  const errBox = qs('login-error');
  const label = qs('login-btn-label');
  errBox.style.display = 'none';
  label.innerHTML = '<span class="spinner"></span> Signing in…';
  try {
    const resp = await Api.login(email, password);
    AuthStore.setToken(resp.token);
    AuthStore.setUser(resp.user);
    location.hash = (resp.user.role === 'VOLUNTEER' || resp.user.role === 'SHELTER_MANAGER')
      ? '#/volunteer/dashboard' : '#/coordinator/dashboard';
  } catch (err) {
    errBox.textContent = err.message || 'Login failed';
    errBox.style.display = 'block';
    label.textContent = 'Sign in';
  }
}

window.renderLogin = renderLogin;
