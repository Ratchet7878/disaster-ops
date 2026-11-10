// Minimal hash-router. No build step needed -- routes match spec section
// 160's frontend route list (collapsed slightly for MVP scope).

const routes = [];

function route(pattern, opts) {
  // pattern like '/coordinator/shelters/:id'
  const paramNames = [];
  const regex = new RegExp(
    '^' + pattern.replace(/:[^/]+/g, (m) => { paramNames.push(m.slice(1)); return '([^/]+)'; }) + '$'
  );
  routes.push({ regex, paramNames, ...opts });
}

function matchRoute(path) {
  for (const r of routes) {
    const m = path.match(r.regex);
    if (m) {
      const params = {};
      r.paramNames.forEach((name, i) => { params[name] = decodeURIComponent(m[i + 1]); });
      return { route: r, params };
    }
  }
  return null;
}

function currentPath() {
  const hash = location.hash || '#/login';
  return hash.slice(1) || '/login';
}

async function renderRoute() {
  const path = currentPath();
  const match = matchRoute(path);
  const user = AuthStore.getUser();
  const token = AuthStore.getToken();

  if (!match) {
    location.hash = user ? defaultRouteFor(user.role) : '#/login';
    return;
  }
  if (match.route.public) {
    if (token && user && path === '/login') {
      location.hash = defaultRouteFor(user.role);
      return;
    }
    return renderInto(match, null);
  }

  if (!token || !user) {
    location.hash = '#/login';
    return;
  }
  if (match.route.roles && !match.route.roles.includes(user.role)) {
    location.hash = defaultRouteFor(user.role);
    return;
  }
  return renderInto(match, user);
}

function defaultRouteFor(role) {
  return (role === 'VOLUNTEER' || role === 'SHELTER_MANAGER') ? '#/volunteer/dashboard' : '#/coordinator/dashboard';
}

async function renderInto(match, user) {
  const app = qs('app');
  if (!user) {
    app.className = '';
    document.body.className = '';
    app.innerHTML = '';
    await match.route.render(match.params, app);
    return;
  }

  const isVolunteer = user.role === 'VOLUNTEER' || user.role === 'SHELTER_MANAGER';
  document.body.className = isVolunteer ? 'volunteer-mode' : '';

  if (isVolunteer) {
    app.innerHTML = Layout.volunteerShell(user);
    const content = qs('v-content');
    await match.route.render(match.params, content);
  } else {
    app.innerHTML = Layout.coordinatorShell(user, currentPath());
    const content = qs('coord-content');
    await match.route.render(match.params, content);
  }
  Layout.wireLogout();
}

window.addEventListener('hashchange', renderRoute);

window.Router = { route, renderRoute, currentPath: () => currentPath() };
