// Stock list, item editor, adjustments and the per-item demand outlook.

import { api, session } from '../api.js';
import {
  badge, barChart, debounce, empty, esc, loading, modal, money, num, statTile,
  table, toast,
} from '../ui.js';

const state = { q: '', category_id: '', supplier_id: '', status: 'active', low_stock: false,
                offset: 0, limit: 100 };
let categories = [];
let suppliers = [];

export async function render(root) {
  root.innerHTML = `
    <div class="page-head">
      <div><h2>Inventory</h2><p id="inv-count" class="muted">Loading…</p></div>
      <div class="page-actions">
        <button class="btn btn-sm" id="inv-export">Export CSV</button>
        <button class="btn btn-sm" id="inv-critical">Critical list</button>
        ${session.can('inventory.edit')
          ? '<button class="btn btn-primary btn-sm" id="inv-new">New item</button>' : ''}
      </div>
    </div>

    <div class="filters">
      <label class="field grow"><span>Search</span>
        <input id="f-q" placeholder="Item code, description or barcode" value="${esc(state.q)}">
      </label>
      <label class="field"><span>Category</span><select id="f-cat"></select></label>
      <label class="field"><span>Supplier</span><select id="f-sup"></select></label>
      <label class="field"><span>Status</span>
        <select id="f-status">
          <option value="active">Active</option>
          <option value="delisted">Delisted</option>
          <option value="all">All</option>
        </select></label>
      <label class="field" style="min-width:auto">
        <span>&nbsp;</span>
        <label style="display:flex;gap:7px;align-items:center;padding:9px 0;font-size:13.5px">
          <input type="checkbox" id="f-low"> Low stock only
        </label>
      </label>
    </div>

    <div class="card"><div id="inv-table">${loading()}</div></div>`;

  [categories, suppliers] = await Promise.all([
    api.get('/api/categories').then((r) => r.categories),
    api.get('/api/suppliers').then((r) => r.suppliers),
  ]);

  const catSelect = document.getElementById('f-cat');
  catSelect.innerHTML = '<option value="">All categories</option>' +
    categories.map((c) => `<option value="${c.id}">${esc(c.name)} (${c.item_count})</option>`).join('');
  const supSelect = document.getElementById('f-sup');
  supSelect.innerHTML = '<option value="">All suppliers</option>' +
    suppliers.map((s) => `<option value="${s.id}">${esc(s.code)} (${s.item_count})</option>`).join('');

  document.getElementById('f-q').addEventListener('input', debounce((event) => {
    state.q = event.target.value; state.offset = 0; load();
  }, 280));
  catSelect.addEventListener('change', (e) => { state.category_id = e.target.value; state.offset = 0; load(); });
  supSelect.addEventListener('change', (e) => { state.supplier_id = e.target.value; state.offset = 0; load(); });
  document.getElementById('f-status').addEventListener('change', (e) => {
    state.status = e.target.value; state.offset = 0; load();
  });
  document.getElementById('f-low').addEventListener('change', (e) => {
    state.low_stock = e.target.checked; state.offset = 0; load();
  });

  document.getElementById('inv-export').addEventListener('click', () =>
    api.download('/api/reports/export/inventory'));
  document.getElementById('inv-critical').addEventListener('click', showCritical);
  document.getElementById('inv-new')?.addEventListener('click', () => openEditor(null));

  load();
}

async function load() {
  const box = document.getElementById('inv-table');
  box.innerHTML = loading();
  try {
    const data = await api.get('/api/items', state);
    document.getElementById('inv-count').textContent =
      `${num(data.total)} items match${state.low_stock ? ' (low stock only)' : ''}`;

    box.innerHTML = table([
      { label: 'Code', render: (r) => `<span class="faint">${esc(r.sku)}</span>`, nowrap: true },
      { label: 'Description', render: (r) => `<strong>${esc(r.description)}</strong>` },
      { label: 'Category', render: (r) => `<span class="muted">${esc(r.category || '—')}</span>` },
      { label: 'Supplier', render: (r) => `<span class="muted">${esc(r.supplier || '—')}</span>` },
      { label: 'Cost', align: 'right', render: (r) => money(r.unit_cost) },
      { label: 'Price', align: 'right', render: (r) => money(r.retail_price) },
      { label: 'Margin', align: 'right', render: (r) => {
          const margin = Number(r.retail_price) - Number(r.unit_cost);
          const colour = margin <= 0 ? 'var(--danger)' : 'var(--text)';
          return `<span style="color:${colour}">${money(margin)}</span>`;
        } },
      { label: 'On hand', align: 'right', render: (r) => {
          const qty = Number(r.stock_qty);
          if (qty <= 0) return badge('none', 'danger');
          if (qty <= Number(r.reorder_point)) return badge(num(qty), 'warn');
          return num(qty);
        } },
      { label: 'Value', align: 'right',
        render: (r) => money(Number(r.stock_qty) * Number(r.unit_cost)) },
    ], data.items, {
      emptyMessage: 'No items match those filters',
      rowAttrs: (r) => `data-item="${r.id}"`,
      onRowClick: true,
    }) + pager(data.total);

    box.querySelectorAll('[data-item]').forEach((row) => {
      row.addEventListener('click', () => openItem(Number(row.dataset.item)));
    });
    box.querySelector('[data-prev]')?.addEventListener('click', () => {
      state.offset = Math.max(0, state.offset - state.limit); load();
    });
    box.querySelector('[data-next]')?.addEventListener('click', () => {
      state.offset += state.limit; load();
    });
  } catch (error) {
    box.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function pager(total) {
  if (total <= state.limit) return '';
  const from = state.offset + 1;
  const to = Math.min(state.offset + state.limit, total);
  return `
    <div style="display:flex;justify-content:space-between;align-items:center;
                padding:12px 4px 0;gap:10px">
      <span class="faint" style="font-size:12.5px">Showing ${from}–${to} of ${num(total)}</span>
      <span style="display:flex;gap:8px">
        <button class="btn btn-sm" data-prev ${state.offset === 0 ? 'disabled' : ''}>Previous</button>
        <button class="btn btn-sm" data-next ${to >= total ? 'disabled' : ''}>Next</button>
      </span>
    </div>`;
}

async function openItem(itemId) {
  const close = modal({ title: 'Item', body: loading(), wide: true });
  void close;

  try {
    const [detail, outlook] = await Promise.all([
      api.get(`/api/items/${itemId}`),
      session.can('analytics.view')
        ? api.get(`/api/analytics/items/${itemId}/forecast`, { days: 180 }).catch(() => null)
        : Promise.resolve(null),
    ]);
    document.querySelector('.modal-backdrop:last-child')?.remove();
    showItem(detail, outlook);
  } catch (error) {
    toast(error.message, 'error');
  }
}

function showItem(detail, outlook) {
  const item = detail.item;
  const margin = Number(item.retail_price) - Number(item.unit_cost);
  const marginPct = Number(item.retail_price) > 0
    ? (margin / Number(item.retail_price)) * 100 : 0;

  const forecastPane = outlook ? `
    <div class="grid grid-4" style="margin-top:16px">
      ${statTile({ label: 'Demand pattern', value: esc(outlook.pattern.pattern),
                   sub: `forecast by ${esc(outlook.pattern.method || 'n/a')}` })}
      ${statTile({ label: 'Next 30 days', value: num(outlook.forecast.next_30d, 1),
                   tone: 'info', sub: 'units expected to sell' })}
      ${statTile({ label: 'Reorder point', value: num(outlook.replenishment.reorder_point, 1),
                   tone: 'warn',
                   sub: `safety stock ${num(outlook.replenishment.safety_stock, 1)}` })}
      ${statTile({ label: 'Days of cover',
                   value: outlook.replenishment.days_of_cover === null
                     ? '∞' : num(outlook.replenishment.days_of_cover, 0),
                   tone: outlook.replenishment.days_of_cover !== null
                     && outlook.replenishment.days_of_cover < outlook.replenishment.lead_time_days
                     ? 'danger' : 'ok',
                   sub: outlook.replenishment.projected_stockout
                     ? `runs out ~${esc(outlook.replenishment.projected_stockout)}`
                     : 'no stockout projected' })}
    </div>
    <div class="card" style="margin-top:14px">
      <div class="card-head"><h3>Weekly demand</h3>
        <span class="hint">from ${esc(outlook.window.measured_from)}</span></div>
      ${barChart(outlook.weekly_demand.map((w) => ({ label: w.week_of, value: w.qty })),
                 { height: 110 })}
    </div>
    <div class="card">
      <div class="card-head"><h3>Suggested order</h3></div>
      <dl class="kv">
        <dt>Economic order quantity</dt>
        <dd>${num(outlook.replenishment.economic_order_qty, 0)} units</dd>
        <dt>Supplier lead time</dt><dd>${num(outlook.replenishment.lead_time_days)} days</dd>
        <dt>Review cycle</dt><dd>${num(outlook.replenishment.review_days)} days</dd>
      </dl>
    </div>` : '';

  const history = detail.history.length ? `
    <div class="card">
      <div class="card-head"><h3>Imported monthly history</h3></div>
      ${table([
        { label: 'Month', key: 'period' },
        { label: 'Qty sold', align: 'right', render: (r) => num(r.qty) },
        { label: 'Revenue', align: 'right', render: (r) => money(r.revenue) },
      ], detail.history)}
    </div>` : '';

  modal({
    title: item.description,
    wide: true,
    body: `
      <div class="grid grid-4">
        ${statTile({ label: 'On hand', value: num(item.stock_qty),
                     tone: item.stock_qty <= 0 ? 'danger'
                       : item.stock_qty <= item.reorder_point ? 'warn' : 'ok',
                     sub: `reorder at ${num(item.reorder_point)}` })}
        ${statTile({ label: 'Unit cost', value: money(item.unit_cost),
                     sub: `stock value ${money(item.stock_qty * item.unit_cost)}` })}
        ${statTile({ label: 'Retail price', value: money(item.retail_price),
                     sub: `margin ${money(margin)} (${marginPct.toFixed(1)}%)`,
                     tone: margin <= 0 ? 'danger' : '' })}
        ${statTile({ label: 'Item code', value: esc(item.sku),
                     sub: `${esc(item.category || '—')} · ${esc(item.supplier || '—')}` })}
      </div>
      ${forecastPane}
      ${history}
      <div class="card">
        <div class="card-head"><h3>Stock movements</h3>
          <span class="hint">most recent first</span></div>
        ${table([
          { label: 'When', render: (r) => `<span class="faint">${esc(String(r.ts).slice(0, 16))}</span>`,
            nowrap: true },
          { label: 'Type', render: (r) => badge(r.move_type,
              r.qty_delta > 0 ? 'ok' : r.move_type === 'sale' ? 'medium' : 'warn') },
          { label: 'Change', align: 'right', render: (r) =>
              `<span style="color:${r.qty_delta > 0 ? 'var(--ok)' : 'var(--danger)'}">
                 ${r.qty_delta > 0 ? '+' : ''}${num(r.qty_delta)}</span>` },
          { label: 'Balance', align: 'right', render: (r) => num(r.balance_after) },
          { label: 'Note', render: (r) => `<span class="faint">${esc(r.note || '')}</span>` },
        ], detail.moves, { emptyMessage: 'No movements recorded yet' })}
      </div>`,
    footer: `
      <button class="btn" data-close>Close</button>
      ${session.can('inventory.adjust')
        ? `<button class="btn" id="item-adjust">Adjust stock</button>` : ''}
      ${session.can('inventory.edit')
        ? `<button class="btn btn-primary" id="item-edit">Edit item</button>` : ''}`,
    onMount: (root, close) => {
      root.querySelector('#item-edit')?.addEventListener('click', () => {
        close(); openEditor(item);
      });
      root.querySelector('#item-adjust')?.addEventListener('click', () => {
        close(); openAdjust(item);
      });
    },
  });
}

function openEditor(item) {
  const isNew = !item;
  const value = (key, fallback = '') => esc(item ? (item[key] ?? fallback) : fallback);

  modal({
    title: isNew ? 'New item' : `Edit ${item.description}`,
    body: `
      <label class="field"><span>Description</span>
        <input id="i-desc" value="${value('description')}" required></label>
      <div class="grid grid-2">
        <label class="field"><span>Category</span><select id="i-cat">
          <option value="">—</option>
          ${categories.map((c) => `<option value="${c.id}"
            ${item && item.category_id === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
        </select></label>
        <label class="field"><span>Supplier</span><select id="i-sup">
          <option value="">—</option>
          ${suppliers.map((s) => `<option value="${s.id}"
            ${item && item.supplier_id === s.id ? 'selected' : ''}>${esc(s.code)}</option>`).join('')}
        </select></label>
        <label class="field"><span>Unit cost</span>
          <input id="i-cost" type="number" step="0.01" min="0" value="${value('unit_cost', 0)}"></label>
        <label class="field"><span>Retail price</span>
          <input id="i-price" type="number" step="0.01" min="0"
                 value="${value('retail_price', 0)}"></label>
        ${isNew ? `<label class="field"><span>Opening stock</span>
          <input id="i-stock" type="number" step="1" min="0" value="0"></label>` : ''}
        <label class="field"><span>Reorder point</span>
          <input id="i-rop" type="number" step="1" min="0" value="${value('reorder_point', 1)}"></label>
        <label class="field"><span>Barcode</span>
          <input id="i-barcode" value="${value('barcode')}"></label>
        <label class="field"><span>Shelf location</span>
          <input id="i-loc" value="${value('location')}"></label>
      </div>
      <div id="i-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-primary" id="i-save">${isNew ? 'Create item' : 'Save changes'}</button>`,
    onMount: (root, close) => {
      root.querySelector('#i-save').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        const errorBox = root.querySelector('#i-error');
        errorBox.hidden = true;

        const payload = {
          description: root.querySelector('#i-desc').value.trim(),
          category_id: Number(root.querySelector('#i-cat').value) || null,
          supplier_id: Number(root.querySelector('#i-sup').value) || null,
          unit_cost: Number(root.querySelector('#i-cost').value) || 0,
          retail_price: Number(root.querySelector('#i-price').value) || 0,
          reorder_point: Number(root.querySelector('#i-rop').value) || 0,
          barcode: root.querySelector('#i-barcode').value.trim() || null,
          location: root.querySelector('#i-loc').value.trim(),
        };
        if (isNew) payload.stock_qty = Number(root.querySelector('#i-stock').value) || 0;

        if (!payload.description) {
          errorBox.textContent = 'A description is required.';
          errorBox.hidden = false;
          button.disabled = false;
          return;
        }

        try {
          if (isNew) await api.post('/api/items', payload);
          else await api.patch(`/api/items/${item.id}`, payload);
          close();
          toast(isNew ? 'Item created' : 'Item saved', 'ok');
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

function openAdjust(item) {
  modal({
    title: `Adjust stock — ${item.description}`,
    body: `
      <p class="muted">Currently <strong>${num(item.stock_qty)}</strong> on hand.</p>
      <label class="field"><span>Change in quantity (negative removes stock)</span>
        <input id="a-qty" type="number" step="1" value="0"></label>
      <label class="field"><span>Reason</span>
        <select id="a-reason">
          <option value="correction">Correction</option>
          <option value="damaged">Damaged</option>
          <option value="lost">Lost</option>
          <option value="expired">Expired</option>
          <option value="found">Found</option>
          <option value="customer_return">Customer return</option>
          <option value="supplier_return">Return to supplier</option>
          <option value="internal_use">Internal / shop use</option>
        </select></label>
      <label class="field"><span>Note</span><input id="a-note"></label>
      <div id="a-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-primary" id="a-save">Apply adjustment</button>`,
    onMount: (root, close) => {
      root.querySelector('#a-save').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        const errorBox = root.querySelector('#a-error');
        errorBox.hidden = true;
        try {
          const result = await api.post('/api/inventory/adjust', {
            item_id: item.id,
            qty_delta: Number(root.querySelector('#a-qty').value) || 0,
            reason: root.querySelector('#a-reason').value,
            note: root.querySelector('#a-note').value,
          });
          close();
          toast(`Stock adjusted — now ${num(result.balance)} on hand`, 'ok');
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

async function showCritical() {
  const close = modal({ title: 'Critical stock', body: loading(), wide: true });
  void close;
  const data = await api.get('/api/inventory/low-stock');
  document.querySelector('.modal-backdrop:last-child')?.remove();

  modal({
    title: `Critical stock — ${data.count} lines`,
    wide: true,
    body: table([
      { label: 'Item', render: (r) => `<strong>${esc(r.description)}</strong>
          <div class="faint" style="font-size:11.5px">${esc(r.sku)}</div>` },
      { label: 'Supplier', render: (r) => esc(r.supplier || '—') },
      { label: 'On hand', align: 'right', render: (r) => num(r.stock_qty) },
      { label: 'Reorder at', align: 'right', render: (r) => num(r.reorder_point) },
      { label: 'Short by', align: 'right', render: (r) => `<strong>${num(r.shortfall)}</strong>` },
      { label: 'Status', render: (r) =>
          badge(r.status, r.status === 'OUT OF STOCK' ? 'danger' : 'warn') },
    ], data.items, { emptyMessage: 'Nothing is below its reorder point' }),
  });
}
