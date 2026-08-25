// Stock intelligence: what sells, what to buy, and what is tying up cash.

import { api, session } from '../api.js';
import {
  badge, confirmDialog, esc, loading, modal, money, num, pct, statTile,
  table, toast, urgencyBar,
} from '../ui.js';

const state = { tab: 'reorder', days: 90, supplier_id: '' };
let suppliers = [];

export async function render(root) {
  root.innerHTML = `
    <div class="page-head">
      <div>
        <h2>Stock intelligence</h2>
        <p>Demand forecasts, movement classes and what to order next.</p>
      </div>
      <div class="page-actions">
        <label class="field" style="margin:0"><span>Look back</span>
          <select id="si-days">
            <option value="30">30 days</option>
            <option value="60">60 days</option>
            <option value="90" selected>90 days</option>
            <option value="180">180 days</option>
            <option value="365">1 year</option>
          </select></label>
        <label class="field" style="margin:0"><span>Supplier</span>
          <select id="si-sup"></select></label>
      </div>
    </div>

    <div class="tab-row">
      <button class="tab active" data-tab="reorder">What to order</button>
      <button class="tab" data-tab="fast">Fast movers</button>
      <button class="tab" data-tab="dead">Dead stock</button>
      <button class="tab" data-tab="abc">ABC / XYZ</button>
    </div>

    <div id="si-body">${loading()}</div>`;

  suppliers = (await api.get('/api/suppliers')).suppliers;
  document.getElementById('si-sup').innerHTML =
    '<option value="">All suppliers</option>' +
    suppliers.map((s) => `<option value="${s.id}">${esc(s.code)}</option>`).join('');

  document.getElementById('si-days').addEventListener('change', (event) => {
    state.days = Number(event.target.value); load();
  });
  document.getElementById('si-sup').addEventListener('change', (event) => {
    state.supplier_id = event.target.value; load();
  });
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
  const box = document.getElementById('si-body');
  box.innerHTML = loading('Crunching the numbers…');
  try {
    if (state.tab === 'reorder') box.innerHTML = await reorderView();
    else if (state.tab === 'abc') box.innerHTML = await abcView();
    else box.innerHTML = await moversView(state.tab);
    wire();
  } catch (error) {
    box.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function wire() {
  document.getElementById('si-auto-po')?.addEventListener('click', async () => {
    const ok = await confirmDialog(
      'Create draft purchase orders for every suggested line, grouped by supplier?',
      { title: 'Build purchase orders' });
    if (!ok) return;
    try {
      const result = await api.post('/api/purchasing/orders/auto', {
        supplier_id: Number(state.supplier_id) || null,
        days: state.days,
      });
      toast(`${result.created} draft purchase order(s) created`, 'ok');
    } catch (error) {
      toast(error.message, 'error');
    }
  });

  document.getElementById('si-export')?.addEventListener('click', () => {
    const dataset = state.tab === 'reorder' ? 'reorder' : 'movers';
    api.download(`/api/reports/export/${dataset}`, { days: state.days });
  });

  document.querySelectorAll('[data-forecast]').forEach((row) => {
    row.addEventListener('click', () => showForecast(Number(row.dataset.forecast)));
  });
}

async function reorderView() {
  const data = await api.get('/api/analytics/reorder', {
    days: state.days, supplier_id: state.supplier_id || undefined,
  });

  const tiles = `
    <div class="grid grid-4">
      ${statTile({ label: 'Lines to order', value: num(data.count), tone: 'accent',
                   sub: `over the last ${state.days} days` })}
      ${statTile({ label: 'Total order cost', value: money(data.total_cost), tone: 'info',
                   sub: 'at current unit cost' })}
      ${statTile({ label: 'Suppliers involved', value: num(data.by_supplier.length),
                   sub: 'separate orders needed' })}
      ${statTile({ label: 'Most urgent',
                   value: data.suggestions.length
                     ? esc(data.suggestions[0].sku) : '—',
                   tone: 'danger',
                   sub: data.suggestions.length
                     ? esc(data.suggestions[0].description.slice(0, 34)) : 'nothing urgent' })}
    </div>`;

  const bySupplier = data.by_supplier.length ? `
    <div class="card">
      <div class="card-head"><h3>By supplier</h3></div>
      ${table([
        { label: 'Supplier', render: (r) => `<strong>${esc(r.supplier)}</strong>` },
        { label: 'Lines', align: 'right', render: (r) => num(r.lines) },
        { label: 'Units', align: 'right', render: (r) => num(r.units) },
        { label: 'Order cost', align: 'right', render: (r) => money(r.cost) },
      ], data.by_supplier)}
    </div>` : '';

  return `
    ${tiles}
    <div class="card" style="margin-top:16px">
      <div class="card-head">
        <h3>Suggested purchases</h3>
        <div style="display:flex;gap:8px">
          <button class="btn btn-sm" id="si-export">Export CSV</button>
          ${session.can('purchasing.edit') && data.count
            ? '<button class="btn btn-primary btn-sm" id="si-auto-po">Build draft orders</button>'
            : ''}
        </div>
      </div>
      ${table([
        { label: 'Urgency', render: (r) => urgencyBar(r.urgency), nowrap: true },
        { label: 'Item', render: (r) => `<strong>${esc(r.description)}</strong>
            <div class="faint" style="font-size:11.5px">
              ${esc(r.sku)} · ${esc(r.supplier || 'no supplier')} ·
              lead ${num(r.lead_time_days)}d</div>` },
        { label: 'Class', render: (r) =>
            `${badge(r.abc, r.abc.toLowerCase())} ${badge(r.movement, r.movement)}` },
        { label: 'On hand', align: 'right', render: (r) =>
            `${num(r.on_hand)}${r.on_order > 0
              ? `<div class="faint" style="font-size:11px">+${num(r.on_order)} on order</div>` : ''}` },
        { label: 'Monthly demand', align: 'right', render: (r) => num(r.monthly_rate, 1) },
        { label: 'Reorder at', align: 'right', render: (r) => num(r.reorder_point, 0) },
        { label: 'Order', align: 'right', render: (r) =>
            `<strong style="color:var(--accent)">${num(r.suggested_qty)}</strong>` },
        { label: 'Cost', align: 'right', render: (r) => money(r.order_cost) },
        { label: 'Why', render: (r) => `<span class="faint">${esc(r.reason)}</span>` },
      ], data.suggestions, {
        emptyMessage: 'Nothing needs reordering for these filters',
        rowAttrs: (r) => `data-forecast="${r.item_id}"`,
        onRowClick: true,
      })}
    </div>`;
}

async function moversView(direction) {
  const data = await api.get('/api/analytics/movers', {
    direction, days: state.days, limit: 100,
  });

  const heading = direction === 'fast'
    ? 'Fastest moving items — keep these in stock'
    : 'Dead stock — cash sitting on the shelf';

  const deadValue = direction === 'dead'
    ? data.items.reduce((sum, row) => sum + Number(row.stock_value), 0) : 0;

  const columns = [
    { label: 'Item', render: (r) => `<strong>${esc(r.description)}</strong>
        <div class="faint" style="font-size:11.5px">${esc(r.sku)} · ${esc(r.category || '')}</div>` },
    { label: 'Movement', render: (r) => `${badge(r.movement, r.movement)}
        ${r.movement_basis === 'history'
          ? '<span class="faint" style="font-size:10.5px"> imported</span>' : ''}` },
    { label: 'Pattern', render: (r) => `<span class="muted">${esc(r.demand_pattern)}</span>` },
    { label: 'Sold', align: 'right', render: (r) => num(r.sold_qty) },
    { label: 'Per month', align: 'right', render: (r) => num(r.monthly_rate, 1) },
    { label: 'On hand', align: 'right', render: (r) => num(r.on_hand) },
    { label: 'Stock value', align: 'right', render: (r) => money(r.stock_value) },
    { label: 'Cover', align: 'right', render: (r) =>
        r.days_of_cover === null ? '<span class="faint">∞</span>' : `${num(r.days_of_cover)}d` },
    { label: 'Last sold', render: (r) =>
        r.last_sold ? esc(r.last_sold) : '<span class="faint">never</span>', nowrap: true },
  ];

  return `
    ${direction === 'dead' ? `<div class="grid grid-3">
      ${statTile({ label: 'Dead lines', value: num(data.count), tone: 'danger' })}
      ${statTile({ label: 'Cash tied up', value: money(deadValue), tone: 'warn',
                   sub: 'consider clearance or return' })}
      ${statTile({ label: 'Window', value: `${state.days} days`,
                   sub: `${esc(data.window.from)} → ${esc(data.window.to)}` })}
    </div>` : ''}
    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>${esc(heading)}</h3>
        <button class="btn btn-sm" id="si-export">Export CSV</button></div>
      ${table(columns, data.items, {
        emptyMessage: 'Nothing to show for this window',
        rowAttrs: (r) => `data-forecast="${r.item_id}"`,
        onRowClick: true,
      })}
    </div>`;
}

async function abcView() {
  const data = await api.get('/api/analytics/abc', { days: state.days });

  const summary = `
    <div class="grid grid-3">
      ${data.summary.map((row) => statTile({
        label: `Class ${row.class}`,
        value: num(row.items),
        tone: row.class === 'A' ? 'accent' : row.class === 'B' ? 'info' : '',
        sub: `${money(row.revenue)} revenue · ${money(row.stock_value)} stock`,
      })).join('')}
    </div>`;

  const graded = data.items.filter((row) => row.daily_rate > 0);

  return `
    ${summary}
    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>Stocking policy by class</h3>
        <span class="hint">A/B/C by value, X/Y/Z by how predictable demand is</span></div>
      ${table([
        { label: 'Cell', render: (r) => badge(r.cell, r.cell[0].toLowerCase()) },
        { label: 'Items', align: 'right', render: (r) => num(r.items) },
        { label: 'Recommended policy', render: (r) => esc(r.policy) },
      ], data.matrix)}
    </div>
    <div class="card">
      <div class="card-head"><h3>Items with measurable demand</h3>
        <span class="hint">${num(graded.length)} of ${num(data.items.length)} lines</span></div>
      ${table([
        { label: 'Item', render: (r) => `<strong>${esc(r.description)}</strong>
            <div class="faint" style="font-size:11.5px">${esc(r.sku)}</div>` },
        { label: 'Class', render: (r) => badge(r.abc_xyz, r.abc.toLowerCase()) },
        { label: 'Demand value', align: 'right', render: (r) => money(r.demand_value) },
        { label: 'Share', align: 'right', render: (r) => pct(r.value_share, 2) },
        { label: 'Cumulative', align: 'right', render: (r) => pct(r.cumulative_share, 1) },
        { label: 'Stock value', align: 'right', render: (r) => money(r.stock_value) },
      ], graded.slice(0, 200), { emptyMessage: 'No demand recorded in this window' })}
    </div>`;
}

async function showForecast(itemId) {
  modal({ title: 'Demand outlook', body: loading(), wide: true });
  try {
    const data = await api.get(`/api/analytics/items/${itemId}/forecast`, { days: 180 });
    document.querySelector('.modal-backdrop:last-child')?.remove();

    const { replenishment: plan, forecast, pattern, item } = data;
    modal({
      title: item.description,
      wide: true,
      body: `
        <div class="grid grid-4">
          ${statTile({ label: 'Pattern', value: esc(pattern.pattern),
                       sub: `via ${esc(pattern.method || '—')}` })}
          ${statTile({ label: 'Next 30 days', value: num(forecast.next_30d, 1), tone: 'info',
                       sub: 'units forecast' })}
          ${statTile({ label: 'Reorder point', value: num(plan.reorder_point, 0), tone: 'warn',
                       sub: `incl. ${num(plan.safety_stock, 0)} safety stock` })}
          ${statTile({ label: 'Order quantity', value: num(plan.economic_order_qty, 0),
                       tone: 'accent', sub: 'economic order quantity' })}
        </div>
        <div class="card" style="margin-top:14px">
          <div class="card-head"><h3>Replenishment plan</h3></div>
          <dl class="kv">
            <dt>On hand now</dt><dd>${num(item.stock_qty)}</dd>
            <dt>Days of cover</dt>
            <dd>${plan.days_of_cover === null ? '∞' : `${num(plan.days_of_cover)} days`}</dd>
            <dt>Projected stockout</dt>
            <dd>${plan.projected_stockout ? esc(plan.projected_stockout) : '—'}</dd>
            <dt>Supplier lead time</dt><dd>${num(plan.lead_time_days)} days</dd>
            <dt>Review cycle</dt><dd>${num(plan.review_days)} days</dd>
          </dl>
        </div>
        <div class="card">
          <div class="card-head"><h3>Demand by weekday</h3>
            <span class="hint">1.0 is an average day</span></div>
          ${table([
            { label: 'Day', key: 'day' },
            { label: 'Index', align: 'right', render: (r) => num(r.index, 2) },
          ], data.weekday_seasonality)}
        </div>`,
    });
  } catch (error) {
    document.querySelector('.modal-backdrop:last-child')?.remove();
    toast(error.message, 'error');
  }
}


