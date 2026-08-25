// Bootstraps the app: authentication gate, navigation and view routing.

import { api, session } from './api.js';
import { el, esc, toast } from './ui.js';

const ROUTES = [
  { id: 'pos',          label: 'Point of Sale', permission: 'pos.sell',
    load: () => import('./views/pos.js') },
  { id: 'dashboard',    label: 'Dashboard',     permission: 'reports.view',
    load: () => import('./views/dashboard.js') },
  { id: 'inventory',    label: 'Inventory',     permission: 'inventory.view',
    load: () => import('./views/inventory.js') },
  { id: 'intelligence', label: 'Stock intelligence', permission: 'analytics.view',
    load: () => import('./views/intelligence.js') },
  { id: 'purchasing',   label: 'Purchasing',    permission: 'purchasing.view',
    load: () => import('./views/purchasing.js') },
  { id: 'reports',      label: 'Reports',       permission: 'reports.view',
    load: () => import('./views/reports.js') },
  { id: 'admin',        label: 'Admin',         permission: 'settings.manage',
    load: () => import('./views/admin.js') },
];

let currentRoute = null;

// ------------------------------------------------------------------ startup

async function start() {
  if (!session.token) return showLogin();
  try {
    const me = await api.get('/api/auth/me');
    session.user = me.user;
    session.permissions = me.permissions;
    if (session.user.must_change_password) return showPasswordChange();
    await showApp();
  } catch {
    showLogin();
  }
}

function show(screen) {
  for (const id of ['login-screen', 'pwchange-screen', 'app']) {
    el(id).hidden = id !== screen;
  }
}

function showLogin(message) {
  show('login-screen');
  const errorBox = el('login-error');
  if (message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  } else {
    errorBox.hidden = true;
  }
  el('login-password').value = '';
  el('login-username').focus();
}

function showPasswordChange() {
  show('pwchange-screen');
  el('pw-current').focus();
}

async function showApp() {
  show('app');

  try {
    const { settings } = await api.get('/api/settings');
    session.settings = settings;
    el('shop-name').textContent = settings.shop_name || 'KYGS';
    document.title = `${settings.shop_name || 'KYGS'} — POS & Inventory`;
  } catch { /* Settings are cosmetic; carry on without them. */ }

  el('user-name').textContent = session.user.full_name || session.user.username;
  el('user-role').textContent = session.user.role;

  const allowed = ROUTES.filter((route) => session.can(route.permission));
  el('main-nav').innerHTML = allowed
    .map((route) => `<button class="nav-btn" data-route="${route.id}">${esc(route.label)}</button>`)
    .join('');

  el('main-nav').querySelectorAll('[data-route]').forEach((button) => {
    button.addEventListener('click', () => navigate(button.dataset.route));
  });

  const wanted = location.hash.slice(1);
  const start = allowed.find((route) => route.id === wanted) || allowed[0];
  if (start) navigate(start.id);
  else el('view').innerHTML =
    '<div class="alert alert-warn">Your account has no screens enabled. ' +
    'Ask an administrator to review your role.</div>';
}

async function navigate(routeId) {
  const route = ROUTES.find((r) => r.id === routeId);
  if (!route || !session.can(route.permission)) return;

  currentRoute = routeId;
  location.hash = routeId;
  el('main-nav').querySelectorAll('[data-route]').forEach((button) => {
    button.classList.toggle('active', button.dataset.route === routeId);
  });

  const view = el('view');
  view.innerHTML = '<div class="loading">Loading…</div>';
  try {
    const module = await route.load();
    if (currentRoute !== routeId) return;  // A newer navigation won the race.
    await module.render(view);
  } catch (error) {
    view.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

// -------------------------------------------------------------------- events

el('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.target.querySelector('button[type="submit"]');
  button.disabled = true;
  el('login-error').hidden = true;

  try {
    const result = await api.login(el('login-username').value.trim(),
                                   el('login-password').value);
    session.token = result.token;
    session.user = result.user;
    session.permissions = result.permissions;
    if (result.user.must_change_password) showPasswordChange();
    else await showApp();
  } catch (error) {
    el('login-error').textContent = error.message;
    el('login-error').hidden = false;
  } finally {
    button.disabled = false;
  }
});

el('pwchange-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const errorBox = el('pw-error');
  errorBox.hidden = true;

  const next = el('pw-new').value;
  if (next !== el('pw-confirm').value) {
    errorBox.textContent = 'The two new passwords do not match.';
    errorBox.hidden = false;
    return;
  }

  try {
    await api.post('/api/auth/change-password', {
      current_password: el('pw-current').value,
      new_password: next,
    });
    const me = await api.get('/api/auth/me');
    session.user = me.user;
    session.permissions = me.permissions;
    toast('Password updated', 'ok');
    await showApp();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
});

el('logout-btn').addEventListener('click', async () => {
  try { await api.post('/api/auth/logout'); } catch { /* Sign out locally regardless. */ }
  session.token = '';
  session.user = null;
  session.permissions = [];
  showLogin();
});

window.addEventListener('kygs:signed-out', () => showLogin('Your session has ended.'));

window.addEventListener('hashchange', () => {
  const wanted = location.hash.slice(1);
  if (wanted && wanted !== currentRoute && session.user) navigate(wanted);
});

start();
