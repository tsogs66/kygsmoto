// Sales, profit, category and cashier reporting.

import { api, session } from '../api.js';
import {
  badge, barChart, daysAgo, empty, esc, loading, money, num, pct,
  statTile, table, toast, today,
} from '../ui.js';

const state = { tab: 'sales', from: daysAgo(29), to: today(), group_by: 'day' };

export async function render(root) {
  root.innerHTML = `
    <div class="page-head">
      <div><h2>Reports</h2><p>Trading performance, margins and till accountability.</p></div>
      <div class="page-actions">
        <label class="field" style="margin:0"><span>From</span>
          <input type="date" id="r-from" value="${state.from}"></label>
        <label class="field" style="margin:0"><span>To</span>
          <input type="date" id="r-to" value="${state.to}"></label>
      </div>
    </div>

    <div class="tab-row">
      <button class="tab active" data-tab="sales">Sales</button>
      <button class="tab" data-tab="items">Top items</button>
      <button class="tab" data-tab="categories">Categories</button>
      <button class="tab" data-tab="cashier">Cashiers &amp; tenders</button>
      ${session.can('reports.financial')
        ? '<button class="tab" data-tab="pnl">Profit &amp; loss</button>' : ''}
      ${session.can('reports.financial')
        ? '<button class="tab" data-tab="valuation">Stock valuation</button>' : ''}
      <button class="tab" data-tab="receipts">Receipts</button>
    </div>

    <div id="r-body">${loading()}</div>`;

  document.getElementById('r-from').addEventListener('change', (event) => {
    state.from = event.target.value; load();
  });
  document.getElementById('r-to').addEventListener('change', (event) => {
    state.to = event.target.value; load();
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

const range = () => ({ date_from: state.from, date_to: state.to });

async function load() {
  const box = document.getElementById('r-body');
  box.innerHTML = loading();
  try {
    const views = {
      sales: salesView, items: itemsView, categories: categoriesView,
      cashier: cashierView, pnl: pnlView, valuation: valuationView, receipts: receiptsView,
    };
    box.innerHTML = await views[state.tab]();
    wire();
  } catch (error) {
    box.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function wire() {
  document.getElementById('r-group')?.addEventListener('change', (event) => {
    state.group_by = event.target.value; load();
  });
  document.getElementById('r-export')?.addEventListener('click', () =>
    api.download('/api/reports/export/sales', range()));
  document.querySelectorAll('[data-receipt]').forEach((row) => {
    row.addEventListener('click', () => openReceipt(Number(row.dataset.receipt)));
  });
}

async function salesView() {
  const data = await api.get('/api/reports/sales-summary', {
    ...range(), group_by: state.group_by,
  });
  const t = data.totals;

  return `
    <div class="grid grid-4">
      ${statTile({ label: 'Net sales', value: money(t.sales), tone: 'accent',
                   sub: `${num(t.receipts)} receipts` })}
      ${statTile({ label: 'Gross profit', value: money(t.profit), tone: 'ok',
                   sub: `${pct(t.margin_pct)} margin` })}
      ${statTile({ label: 'Parts vs labour', value: money(t.parts), tone: 'info',
                   sub: `labour ${money(t.labor)}` })}
      ${statTile({ label: 'Discounts given', value: money(t.discount),
                   tone: t.discount > 0 ? 'warn' : '' })}
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>Sales over time</h3>
        <div style="display:flex;gap:8px;align-items:center">
          <select id="r-group" style="width:auto">
            <option value="day" ${state.group_by === 'day' ? 'selected' : ''}>By day</option>
            <option value="week" ${state.group_by === 'week' ? 'selected' : ''}>By week</option>
            <option value="month" ${state.group_by === 'month' ? 'selected' : ''}>By month</option>
          </select>
          <button class="btn btn-sm" id="r-export">Export CSV</button>
        </div></div>
      ${data.periods.length
        ? barChart(data.periods.map((p) => ({ label: p.period, value: p.sales })),
                   { format: money })
        : empty('No sales in this period')}
    </div>

    <div class="card">
      ${table([
        { label: 'Period', key: 'period', nowrap: true },
        { label: 'Receipts', align: 'right', render: (r) => num(r.receipts) },
        { label: 'Parts', align: 'right', render: (r) => money(r.parts) },
        { label: 'Labour', align: 'right', render: (r) => money(r.labor) },
        { label: 'Discount', align: 'right', render: (r) => money(r.discount) },
        { label: 'Net sales', align: 'right', render: (r) => `<strong>${money(r.sales)}</strong>` },
        { label: 'Cost', align: 'right', render: (r) => money(r.cost) },
        { label: 'Profit', align: 'right', render: (r) =>
            `<span style="color:${r.profit >= 0 ? 'var(--ok)' : 'var(--danger)'}">
               ${money(r.profit)}</span>` },
        { label: 'Margin', align: 'right', render: (r) => pct(r.margin_pct) },
      ], data.periods, { emptyMessage: 'No sales in this period' })}
    </div>`;
}

async function itemsView() {
  const [byRevenue, byQty] = await Promise.all([
    api.get('/api/reports/top-items', { ...range(), by: 'revenue', limit: 25 }),
    api.get('/api/reports/top-items', { ...range(), by: 'qty', limit: 25 }),
  ]);

  const columns = [
    { label: 'Item', render: (r) => `<strong>${esc(r.description)}</strong>
        <div class="faint" style="font-size:11.5px">${esc(r.sku || r.line_type)}</div>` },
    { label: 'Qty', align: 'right', render: (r) => num(r.qty) },
    { label: 'Revenue', align: 'right', render: (r) => money(r.revenue) },
    { label: 'Profit', align: 'right', render: (r) => money(r.profit) },
  ];

  return `
    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h3>Top earners</h3><span class="hint">by revenue</span></div>
        ${table(columns, byRevenue.items)}
      </div>
      <div class="card">
        <div class="card-head"><h3>Highest volume</h3><span class="hint">by units sold</span></div>
        ${table(columns, byQty.items)}
      </div>
    </div>`;
}

async function categoriesView() {
  const data = await api.get('/api/reports/category-performance', range());
  return `
    <div class="card">
      <div class="card-head"><h3>Category performance</h3></div>
      ${data.categories.length
        ? barChart(data.categories.map((c) => ({ label: c.category, value: c.revenue })),
                   { format: money })
        : ''}
      ${table([
        { label: 'Category', render: (r) => `<strong>${esc(r.category)}</strong>` },
        { label: 'Units', align: 'right', render: (r) => num(r.qty) },
        { label: 'Revenue', align: 'right', render: (r) => money(r.revenue) },
        { label: 'Profit', align: 'right', render: (r) => money(r.profit) },
        { label: 'Margin', align: 'right', render: (r) =>
            pct(r.revenue > 0 ? (r.profit / r.revenue) * 100 : 0) },
        { label: 'Stock value', align: 'right', render: (r) => money(r.stock_value) },
      ], data.categories, { emptyMessage: 'No category sales in this period' })}
    </div>`;
}

async function cashierView() {
  const data = await api.get('/api/reports/cashier', range());
  return `
    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h3>By cashier</h3></div>
        ${table([
          { label: 'Cashier', render: (r) => `<strong>${esc(r.username)}</strong>
              <div class="faint" style="font-size:11.5px">${esc(r.full_name || '')}</div>` },
          { label: 'Receipts', align: 'right', render: (r) => num(r.receipts) },
          { label: 'Sales', align: 'right', render: (r) => money(r.sales) },
          { label: 'Discounts', align: 'right', render: (r) => money(r.discounts) },
          { label: 'Profit', align: 'right', render: (r) => money(r.profit) },
        ], data.cashiers, { emptyMessage: 'No sales in this period' })}
      </div>
      <div class="card">
        <div class="card-head"><h3>Tenders taken</h3></div>
        ${table([
          { label: 'Method', render: (r) => badge(r.method, 'medium') },
          { label: 'Count', align: 'right', render: (r) => num(r.count) },
          { label: 'Amount', align: 'right', render: (r) => money(r.amount) },
        ], data.tenders, { emptyMessage: 'No payments recorded' })}
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Voided sales</h3>
        <span class="hint">every void is logged against the user who made it</span></div>
      ${table([
        { label: 'Receipt', render: (r) => esc(r.receipt_no), nowrap: true },
        { label: 'Value', align: 'right', render: (r) => money(r.total) },
        { label: 'Voided by', render: (r) => esc(r.voided_by || '—') },
        { label: 'When', render: (r) => esc(String(r.voided_at || '').slice(0, 16)), nowrap: true },
        { label: 'Reason', render: (r) => `<span class="faint">${esc(r.void_reason)}</span>` },
      ], data.voids, { emptyMessage: 'No voids in this period — good' })}
    </div>`;
}

async function pnlView() {
  const data = await api.get('/api/reports/profit-and-loss', range());
  return `
    <div class="grid grid-4">
      ${statTile({ label: 'Net sales', value: money(data.net_sales), tone: 'accent',
                   sub: `${num(data.receipts)} receipts` })}
      ${statTile({ label: 'Total gross profit', value: money(data.total_gross_profit),
                   tone: 'ok', sub: `${pct(data.gross_margin_pct)} margin` })}
      ${statTile({ label: 'Service income', value: money(data.service_income), tone: 'info',
                   sub: 'labour, no cost of goods' })}
      ${statTile({ label: 'Stock purchased', value: money(data.stock_purchased),
                   sub: 'deliveries booked in' })}
    </div>
    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>Trading account
        <span class="muted" style="font-weight:400">
          ${esc(data.range.from)} → ${esc(data.range.to)}</span></h3></div>
      <dl class="kv" style="max-width:520px">
        <dt>Parts sales</dt><dd>${money(data.parts_sales)}</dd>
        <dt>Service income</dt><dd>${money(data.service_income)}</dd>
        <dt>Less: discounts given</dt><dd>−${money(data.discounts_given)}</dd>
        <dt class="strong">Net sales</dt><dd class="strong">${money(data.net_sales)}</dd>
        <dt>Less: cost of goods sold</dt><dd>−${money(data.cost_of_goods_sold)}</dd>
        <dt>Gross profit on parts</dt><dd>${money(data.gross_profit_on_parts)}</dd>
        <dt class="strong">Total gross profit</dt>
        <dd class="strong">${money(data.total_gross_profit)}</dd>
      </dl>
      <p class="faint" style="margin-top:14px;font-size:12.5px">
        Operating expenses (rent, wages, utilities) are not tracked by the till, so this is a
        trading account rather than a full profit and loss statement.</p>
    </div>`;
}

async function valuationView() {
  const data = await api.get('/api/reports/inventory-valuation');
  const t = data.totals;
  return `
    <div class="grid grid-4">
      ${statTile({ label: 'Stock at cost', value: money(t.cost_value), tone: 'accent',
                   sub: `${num(t.skus)} SKUs · ${num(t.units)} units` })}
      ${statTile({ label: 'Stock at retail', value: money(t.retail_value), tone: 'info' })}
      ${statTile({ label: 'Potential margin', value: money(t.potential_margin), tone: 'ok',
                   sub: 'if everything sold at list price' })}
      ${statTile({ label: 'Average cost per SKU',
                   value: money(t.skus ? t.cost_value / t.skus : 0) })}
    </div>
    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>Valuation by category</h3></div>
      ${table([
        { label: 'Category', render: (r) => `<strong>${esc(r.category)}</strong>` },
        { label: 'SKUs', align: 'right', render: (r) => num(r.skus) },
        { label: 'Units', align: 'right', render: (r) => num(r.units) },
        { label: 'At cost', align: 'right', render: (r) => money(r.cost_value) },
        { label: 'At retail', align: 'right', render: (r) => money(r.retail_value) },
        { label: 'Potential margin', align: 'right', render: (r) => money(r.potential_margin) },
      ], data.categories)}
    </div>`;
}

async function receiptsView() {
  const data = await api.get('/api/pos/sales', { ...range(), limit: 300 });
  return `
    <div class="card">
      <div class="card-head"><h3>Receipts</h3>
        <span class="hint">${num(data.total)} in this period — click to reprint</span></div>
      ${table([
        { label: 'Receipt', render: (r) => `<strong>${esc(r.receipt_no)}</strong>`, nowrap: true },
        { label: 'When', render: (r) => esc(String(r.ts).slice(0, 16)), nowrap: true },
        { label: 'Cashier', render: (r) => esc(r.cashier) },
        { label: 'Customer', render: (r) => esc(r.customer_name || '—') },
        { label: 'Total', align: 'right', render: (r) => money(r.total) },
        { label: 'Profit', align: 'right', render: (r) => money(r.profit) },
        { label: 'Status', render: (r) =>
            badge(r.status, r.status === 'voided' ? 'danger' : 'ok') },
      ], data.sales, {
        emptyMessage: 'No receipts in this period',
        rowAttrs: (r) => `data-receipt="${r.id}"`,
        onRowClick: true,
      })}
    </div>`;
}

async function openReceipt(saleId) {
  try {
    const payload = await api.get(`/api/pos/sales/${saleId}`);
    const { showReceipt } = await import('./pos.js');
    showReceipt(payload);
  } catch (error) {
    toast(error.message, 'error');
  }
}


