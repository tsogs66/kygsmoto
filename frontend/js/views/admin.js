// Users, shop settings, suppliers, services and the audit trail.

import { api, session } from '../api.js';
import {
  badge, confirmDialog, esc, loading, modal, money, num, statTile, table, toast,
} from '../ui.js';

const state = { tab: 'users' };

export async function render(root) {
  root.innerHTML = `
    <div class="page-head">
      <div><h2>Administration</h2><p>Accounts, shop details and the activity log.</p></div>
    </div>
    <div class="tab-row">
      ${session.can('users.manage')
        ? '<button class="tab active" data-tab="users">Users</button>' : ''}
      <button class="tab ${session.can('users.manage') ? '' : 'active'}"
              data-tab="suppliers">Suppliers</button>
      <button class="tab" data-tab="services">Services</button>
      ${session.can('settings.manage')
        ? '<button class="tab" data-tab="settings">Shop settings</button>' : ''}
      ${session.can('audit.view')
        ? '<button class="tab" data-tab="audit">Audit log</button>' : ''}
    </div>
    <div id="admin-body">${loading()}</div>`;

  if (!session.can('users.manage')) state.tab = 'suppliers';

  root.querySelectorAll('[data-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      state.tab = tab.dataset.tab;
      root.querySelectorAll('[data-tab]').forEach((t) => t.classList.toggle('active', t === tab));
      load();
    });
  });
  load();
}

async function load() {
  const box = document.getElementById('admin-body');
  box.innerHTML = loading();
  try {
    const views = { users: usersView, suppliers: suppliersView, services: servicesView,
                    settings: settingsView, audit: auditView };
    box.innerHTML = await views[state.tab]();
    wire();
  } catch (error) {
    box.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function wire() {
  document.getElementById('u-new')?.addEventListener('click', () => openUser(null));
  document.querySelectorAll('[data-user]').forEach((button) => {
    button.addEventListener('click', async () => {
      const { users } = await api.get('/api/auth/users');
      openUser(users.find((u) => u.id === Number(button.dataset.user)));
    });
  });
  document.querySelectorAll('[data-reset]').forEach((button) => {
    button.addEventListener('click', () => openReset(Number(button.dataset.reset),
                                                     button.dataset.username));
  });
  document.querySelectorAll('[data-toggle]').forEach((button) => {
    button.addEventListener('click', async () => {
      const activate = button.dataset.active === '0';
      const ok = await confirmDialog(
        `${activate ? 'Re-enable' : 'Disable'} ${button.dataset.username}?`,
        { danger: !activate });
      if (!ok) return;
      try {
        await api.patch(`/api/auth/users/${button.dataset.toggle}`, { active: activate });
        toast(`Account ${activate ? 'enabled' : 'disabled'}`, 'ok');
        load();
      } catch (error) { toast(error.message, 'error'); }
    });
  });
  document.getElementById('sup-new')?.addEventListener('click', () => openSupplier(null));
  document.querySelectorAll('[data-supplier]').forEach((row) => {
    row.addEventListener('click', async () => {
      const { suppliers } = await api.get('/api/suppliers');
      openSupplier(suppliers.find((s) => s.id === Number(row.dataset.supplier)));
    });
  });
  document.getElementById('svc-new')?.addEventListener('click', () => openService(null));
  document.querySelectorAll('[data-service]').forEach((row) => {
    row.addEventListener('click', async () => {
      const { services } = await api.get('/api/services', { active_only: false });
      openService(services.find((s) => s.id === Number(row.dataset.service)));
    });
  });
  document.getElementById('settings-save')?.addEventListener('click', saveSettings);
}

// --------------------------------------------------------------------- users

async function usersView() {
  const { users } = await api.get('/api/auth/users');
  return `
    <div class="card">
      <div class="card-head"><h3>User accounts</h3>
        <button class="btn btn-primary btn-sm" id="u-new">Add user</button></div>
      ${table([
        { label: 'Username', render: (r) => `<strong>${esc(r.username)}</strong>` },
        { label: 'Name', render: (r) => esc(r.full_name || '—') },
        { label: 'Role', render: (r) => badge(r.role,
            r.role === 'admin' ? 'a' : r.role === 'manager' ? 'b' : 'c') },
        { label: 'Status', render: (r) => r.active
            ? badge('active', 'ok')
            : badge('disabled', 'danger') },
        { label: 'Last login', render: (r) => r.last_login_at
            ? esc(String(r.last_login_at).slice(0, 16))
            : '<span class="faint">never</span>', nowrap: true },
        { label: '', nowrap: true, render: (r) => `
            <button class="btn btn-sm" data-user="${r.id}">Edit</button>
            <button class="btn btn-sm" data-reset="${r.id}"
                    data-username="${esc(r.username)}">Reset password</button>
            <button class="btn btn-sm ${r.active ? 'btn-danger' : ''}"
                    data-toggle="${r.id}" data-active="${r.active ? 1 : 0}"
                    data-username="${esc(r.username)}">
              ${r.active ? 'Disable' : 'Enable'}</button>` },
      ], users)}
    </div>
    <div class="card">
      <div class="card-head"><h3>What each role can do</h3></div>
      ${table([
        { label: 'Role', render: (r) => badge(r.role, r.tone) },
        { label: 'Can do', render: (r) => esc(r.summary) },
      ], [
        { role: 'cashier', tone: 'c',
          summary: 'Sell at the till, look up stock, see basic sales figures. No discounts, ' +
                   'no voids, no cost prices in reports.' },
        { role: 'manager', tone: 'b',
          summary: 'Everything a cashier can, plus discounts, voids, stock adjustments, ' +
                   'purchasing, forecasting and financial reports.' },
        { role: 'admin', tone: 'a',
          summary: 'Everything a manager can, plus user accounts and data import.' },
      ])}
    </div>`;
}

function openUser(user) {
  const isNew = !user;
  modal({
    title: isNew ? 'Add user' : `Edit ${user.username}`,
    body: `
      <label class="field"><span>Username</span>
        <input id="u-username" value="${isNew ? '' : esc(user.username)}"
               ${isNew ? '' : 'disabled'}></label>
      <label class="field"><span>Full name</span>
        <input id="u-name" value="${isNew ? '' : esc(user.full_name)}"></label>
      <label class="field"><span>Role</span>
        <select id="u-role">
          ${['cashier', 'manager', 'admin'].map((role) =>
            `<option value="${role}" ${!isNew && user.role === role ? 'selected' : ''}>
               ${role}</option>`).join('')}
        </select></label>
      ${isNew ? `<label class="field"><span>Temporary password</span>
        <input id="u-password" type="text" autocomplete="new-password">
        <span class="faint" style="font-size:12px">At least 8 characters, with a letter and a
          digit. They will be asked to change it at first sign-in.</span></label>` : ''}
      <div id="u-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-primary" id="u-save">${isNew ? 'Create' : 'Save'}</button>`,
    onMount: (root, close) => {
      root.querySelector('#u-save').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        const errorBox = root.querySelector('#u-error');
        errorBox.hidden = true;
        try {
          if (isNew) {
            await api.post('/api/auth/users', {
              username: root.querySelector('#u-username').value.trim(),
              full_name: root.querySelector('#u-name').value.trim(),
              password: root.querySelector('#u-password').value,
              role: root.querySelector('#u-role').value,
            });
          } else {
            await api.patch(`/api/auth/users/${user.id}`, {
              full_name: root.querySelector('#u-name').value.trim(),
              role: root.querySelector('#u-role').value,
            });
          }
          close();
          toast(isNew ? 'User created' : 'User updated', 'ok');
          load();
        } catch (error) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
          button.disabled = false;
        }
      });
    },
  });
}

function openReset(userId, username) {
  modal({
    title: `Reset password — ${username}`,
    body: `
      <p class="muted">The user will be signed out everywhere and asked to choose a new
        password at their next sign-in.</p>
      <label class="field"><span>Temporary password</span>
        <input id="pr-password" type="text" autocomplete="new-password"></label>
      <div id="pr-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-danger" id="pr-save">Reset password</button>`,
    onMount: (root, close) => {
      root.querySelector('#pr-save').addEventListener('click', async (event) => {
        event.currentTarget.disabled = true;
        const errorBox = root.querySelector('#pr-error');
        errorBox.hidden = true;
        try {
          await api.post(`/api/auth/users/${userId}/reset-password`, {
            new_password: root.querySelector('#pr-password').value,
          });
          close();
          toast('Password reset', 'ok');
        } catch (error) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
          event.currentTarget.disabled = false;
        }
      });
    },
  });
}

// ----------------------------------------------------------------- suppliers

async function suppliersView() {
  const { suppliers } = await api.get('/api/suppliers');
  return `
    <div class="card">
      <div class="card-head"><h3>Suppliers</h3>
        <span class="hint">lead time drives the reorder point — keep it accurate</span>
        ${session.can('inventory.edit')
          ? '<button class="btn btn-primary btn-sm" id="sup-new">Add supplier</button>' : ''}
      </div>
      ${table([
        { label: 'Code', render: (r) => `<strong>${esc(r.code)}</strong>` },
        { label: 'Name', render: (r) => esc(r.name || '—') },
        { label: 'Contact', render: (r) => esc(r.contact || r.phone || '—') },
        { label: 'Lead time', align: 'right', render: (r) => `${num(r.lead_time_days)} d` },
        { label: 'Order cycle', align: 'right', render: (r) => `${num(r.order_cycle_days)} d` },
        { label: 'Items', align: 'right', render: (r) => num(r.item_count) },
        { label: 'Stock value', align: 'right', render: (r) => money(r.stock_value) },
        { label: 'Status', render: (r) => r.active ? badge('active', 'ok') : badge('inactive') },
      ], suppliers, {
        rowAttrs: (r) => session.can('inventory.edit') ? `data-supplier="${r.id}"` : '',
        onRowClick: session.can('inventory.edit'),
      })}
    </div>`;
}

function openSupplier(supplier) {
  const isNew = !supplier;
  const value = (key, fallback = '') => esc(supplier ? (supplier[key] ?? fallback) : fallback);

  modal({
    title: isNew ? 'Add supplier' : `Edit ${supplier.code}`,
    body: `
      <div class="grid grid-2">
        <label class="field"><span>Code</span><input id="s-code" value="${value('code')}"></label>
        <label class="field"><span>Name</span><input id="s-name" value="${value('name')}"></label>
        <label class="field"><span>Contact person</span>
          <input id="s-contact" value="${value('contact')}"></label>
        <label class="field"><span>Phone</span><input id="s-phone" value="${value('phone')}"></label>
        <label class="field"><span>Lead time (days)</span>
          <input id="s-lead" type="number" min="0" step="0.5"
                 value="${value('lead_time_days', 7)}">
          <span class="faint" style="font-size:12px">How long from ordering to delivery.</span>
        </label>
        <label class="field"><span>Order cycle (days)</span>
          <input id="s-cycle" type="number" min="0" step="1"
                 value="${value('order_cycle_days', 30)}">
          <span class="faint" style="font-size:12px">How often you place an order with them.</span>
        </label>
      </div>
      <div id="s-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-primary" id="s-save">Save</button>`,
    onMount: (root, close) => {
      root.querySelector('#s-save').addEventListener('click', async (event) => {
        event.currentTarget.disabled = true;
        const errorBox = root.querySelector('#s-error');
        errorBox.hidden = true;
        const payload = {
          code: root.querySelector('#s-code').value.trim(),
          name: root.querySelector('#s-name').value.trim(),
          contact: root.querySelector('#s-contact').value.trim(),
          phone: root.querySelector('#s-phone').value.trim(),
          lead_time_days: Number(root.querySelector('#s-lead').value) || 0,
          order_cycle_days: Number(root.querySelector('#s-cycle').value) || 0,
          active: true,
        };
        try {
          if (isNew) await api.post('/api/suppliers', payload);
          else await api.patch(`/api/suppliers/${supplier.id}`, payload);
          close();
          toast('Supplier saved', 'ok');
          load();
        } catch (error) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
          event.currentTarget.disabled = false;
        }
      });
    },
  });
}

// ------------------------------------------------------------------ services

async function servicesView() {
  const { services } = await api.get('/api/services', { active_only: false });
  return `
    <div class="card">
      <div class="card-head"><h3>Labour rates</h3>
        <span class="hint">${num(services.length)} services offered</span>
        ${session.can('inventory.edit')
          ? '<button class="btn btn-primary btn-sm" id="svc-new">Add service</button>' : ''}
      </div>
      ${table([
        { label: 'Code', render: (r) => `<span class="faint">${esc(r.code)}</span>` },
        { label: 'Service', render: (r) => `<strong>${esc(r.name)}</strong>` },
        { label: 'Fee', align: 'right', render: (r) => money(r.fee) },
        { label: 'Status', render: (r) => r.active ? badge('active', 'ok') : badge('inactive') },
      ], services, {
        rowAttrs: (r) => session.can('inventory.edit') ? `data-service="${r.id}"` : '',
        onRowClick: session.can('inventory.edit'),
      })}
    </div>`;
}

function openService(service) {
  const isNew = !service;
  modal({
    title: isNew ? 'Add service' : `Edit ${service.name}`,
    body: `
      <label class="field"><span>Service name</span>
        <input id="v-name" value="${isNew ? '' : esc(service.name)}"></label>
      <label class="field"><span>Labour fee</span>
        <input id="v-fee" type="number" min="0" step="0.01"
               value="${isNew ? 0 : esc(service.fee)}"></label>
      ${isNew ? '' : `<label class="field"
        style="display:flex;gap:8px;align-items:center">
        <input type="checkbox" id="v-active" ${service.active ? 'checked' : ''}
               style="width:auto"> <span>Active</span></label>`}
      <div id="v-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-primary" id="v-save">Save</button>`,
    onMount: (root, close) => {
      root.querySelector('#v-save').addEventListener('click', async (event) => {
        event.currentTarget.disabled = true;
        const errorBox = root.querySelector('#v-error');
        errorBox.hidden = true;
        const payload = {
          name: root.querySelector('#v-name').value.trim(),
          fee: Number(root.querySelector('#v-fee').value) || 0,
          active: isNew ? true : root.querySelector('#v-active').checked,
        };
        try {
          if (isNew) await api.post('/api/services', payload);
          else await api.patch(`/api/services/${service.id}`, payload);
          close();
          toast('Service saved', 'ok');
          load();
        } catch (error) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
          event.currentTarget.disabled = false;
        }
      });
    },
  });
}

// ------------------------------------------------------------------ settings

const SETTING_LABELS = {
  shop_name: 'Shop name',
  shop_address: 'Address (printed on receipts)',
  shop_phone: 'Phone number',
  currency_symbol: 'Currency symbol',
  receipt_footer: 'Receipt footer message',
  low_stock_default: 'Default reorder point for new items',
  service_level_z: 'Service level factor (1.65 ≈ 95% availability)',
  default_lead_time_days: 'Default supplier lead time (days)',
  session_hours: 'Sign-in session length (hours)',
};

async function settingsView() {
  const [{ settings, editable }, health] = await Promise.all([
    api.get('/api/settings'),
    api.get('/api/settings/health').catch(() => null),
  ]);

  const warnings = health ? Object.entries(health.warnings)
    .filter(([, count]) => count > 0) : [];

  return `
    <div class="card">
      <div class="card-head"><h3>Shop settings</h3></div>
      ${editable.map((key) => `
        <label class="field"><span>${esc(SETTING_LABELS[key] || key)}</span>
          <input data-setting="${esc(key)}" value="${esc(settings[key] ?? '')}"></label>`).join('')}
      <button class="btn btn-primary" id="settings-save">Save settings</button>
    </div>
    ${health ? `
    <div class="card">
      <div class="card-head"><h3>Data health</h3>
        <span class="hint">${esc(health.database)}</span></div>
      ${warnings.length
        ? `<div class="alert alert-warn">${warnings.map(([key, count]) =>
             `${esc(key.replace(/_/g, ' '))}: <strong>${num(count)}</strong>`).join(' · ')}</div>`
        : '<div class="alert alert-info">No data problems detected.</div>'}
      <div class="grid grid-4">
        ${Object.entries(health.counts).map(([name, count]) =>
          statTile({ label: name.replace(/_/g, ' '), value: num(count) })).join('')}
      </div>
    </div>` : ''}`;
}

async function saveSettings() {
  const values = {};
  document.querySelectorAll('[data-setting]').forEach((input) => {
    values[input.dataset.setting] = input.value;
  });
  try {
    await api.put('/api/settings', { values });
    toast('Settings saved', 'ok');
    const { settings } = await api.get('/api/settings');
    session.settings = settings;
    document.getElementById('shop-name').textContent = settings.shop_name || 'KYGS';
  } catch (error) {
    toast(error.message, 'error');
  }
}

// --------------------------------------------------------------------- audit

async function auditView() {
  const { entries } = await api.get('/api/auth/audit', { limit: 400 });
  return `
    <div class="card">
      <div class="card-head"><h3>Audit log</h3>
        <span class="hint">every sensitive action, newest first</span></div>
      ${table([
        { label: 'When', render: (r) => `<span class="faint">
            ${esc(String(r.ts).slice(0, 16))}</span>`, nowrap: true },
        { label: 'User', render: (r) => esc(r.username) },
        { label: 'Action', render: (r) => badge(r.action,
            r.action.includes('void') || r.action.includes('failed') ? 'danger'
            : r.action.includes('login') ? 'medium' : '') },
        { label: 'Entity', render: (r) => `<span class="muted">
            ${esc(r.entity)}${r.entity_id ? ` #${esc(r.entity_id)}` : ''}</span>` },
        { label: 'Detail', render: (r) => `<span class="faint" style="font-size:12px">
            ${esc(String(r.detail || '').slice(0, 160))}</span>` },
      ], entries, { emptyMessage: 'Nothing logged yet' })}
    </div>`;
}
