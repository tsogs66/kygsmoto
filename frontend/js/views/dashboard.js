// Management overview: today's trade, stock health and what needs attention.

import { api } from '../api.js';
import {
  barChart, empty, esc, loading, money, num, pct, statTile, table,
} from '../ui.js';

export async function render(root) {
  root.innerHTML = `
    <div class="page-head">
      <div><h2>Dashboard</h2><p>How the shop is trading and where the stock risk is.</p></div>
    </div>
    <div id="dash-body">${loading()}</div>`;

  const body = document.getElementById('dash-body');
  try {
    const [reports, stock] = await Promise.all([
      api.get('/api/reports/dashboard'),
      api.get('/api/analytics/overview', { days: 90 }).catch(() => null),
    ]);
    body.innerHTML = view(reports, stock);
  } catch (error) {
    body.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function view(reports, stock) {
  const { today, month, stock: inv, trend } = reports;

  const tiles = [
    statTile({
      label: 'Sales today', value: money(today.sales), tone: 'accent',
      sub: `${num(today.receipts)} receipts · avg ${money(today.average_sale)}`,
    }),
    statTile({
      label: 'Gross profit today', value: money(today.profit), tone: 'ok',
      sub: `parts ${money(today.parts)} · labour ${money(today.labor)}`,
    }),
    statTile({
      label: 'Sales this month', value: money(month.sales), tone: 'info',
      sub: `${num(month.receipts)} receipts · profit ${money(month.profit)}`,
    }),
    statTile({
      label: 'Stock at cost', value: money(inv.cost_value),
      sub: `${num(inv.skus)} SKUs · retail ${money(inv.retail_value)}`,
    }),
  ].join('');

  const alerts = [
    statTile({
      label: 'Out of stock', value: num(inv.out_of_stock),
      tone: inv.out_of_stock > 0 ? 'danger' : 'ok', sub: 'lines with nothing on the shelf',
    }),
    statTile({
      label: 'At or below reorder point', value: num(inv.critical),
      tone: inv.critical > 0 ? 'warn' : 'ok', sub: 'needing a purchase order',
    }),
    stock ? statTile({
      label: 'Dead stock value', value: money(stock.dead_stock_value),
      tone: stock.dead_stock_pct > 25 ? 'danger' : 'warn',
      sub: `${pct(stock.dead_stock_pct)} of stock value tied up`,
    }) : '',
    stock ? statTile({
      label: 'Stock turnover', value: `${num(stock.stock_turnover_annualised, 2)}×`,
      tone: 'info', sub: 'annualised, from the last 90 days',
    }) : '',
  ].join('');

  const urgent = stock && stock.urgent.length
    ? table([
        { label: 'Item', render: (r) => `<strong>${esc(r.description)}</strong>
            <div class="faint" style="font-size:11.5px">${esc(r.sku)} · ${esc(r.supplier)}</div>` },
        { label: 'On hand', align: 'right', render: (r) => num(r.on_hand) },
        { label: 'Suggested', align: 'right',
          render: (r) => `<strong>${num(r.suggested_qty)}</strong>` },
        { label: 'Cost', align: 'right', render: (r) => money(r.order_cost) },
        { label: 'Why', render: (r) => `<span class="faint">${esc(r.reason)}</span>` },
      ], stock.urgent)
    : empty('Nothing urgent — stock levels look healthy', '✅');

  return `
    <div class="grid grid-4">${tiles}</div>
    <div class="grid grid-4" style="margin-top:16px">${alerts}</div>

    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>Sales, last 30 days</h3>
        <span class="hint">daily takings</span></div>
      ${trend.length
        ? barChart(trend.map((d) => ({ label: d.date, value: d.sales })), { format: money })
        : empty('No sales recorded in the last 30 days')}
    </div>

    <div class="card">
      <div class="card-head"><h3>Needs ordering now</h3>
        <span class="hint">ranked by urgency</span></div>
      ${urgent}
    </div>`;
}
