// Purchase orders: raise, send, receive.

import { api, session } from '../api.js';
import {
  badge, esc, loading, modal, money, num, statTile, table, toast,
} from '../ui.js';

const state = { status: '' };

const STATUS_TONE = {
  draft: '', ordered: 'medium', partial: 'warn', received: 'ok', cancelled: 'danger',
};

export async function render(root) {
  root.innerHTML = `
    <div class="page-head">
      <div><h2>Purchasing</h2><p>Orders raised with suppliers and deliveries booked in.</p></div>
      <div class="page-actions">
        <label class="field" style="margin:0"><span>Status</span>
          <select id="po-status">
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="ordered">Ordered</option>
            <option value="partial">Partly received</option>
            <option value="received">Received</option>
            <option value="cancelled">Cancelled</option>
          </select></label>
      </div>
    </div>
    <div id="po-body">${loading()}</div>`;

  document.getElementById('po-status').addEventListener('change', (event) => {
    state.status = event.target.value; load();
  });
  load();
}

async function load() {
  const box = document.getElementById('po-body');
  box.innerHTML = loading();
  try {
    const { orders } = await api.get('/api/purchasing/orders', {
      status: state.status || undefined, limit: 200,
    });

    const open = orders.filter((o) => ['draft', 'ordered', 'partial'].includes(o.status));
    const committed = open.reduce((sum, o) => sum + Number(o.total_cost), 0);

    box.innerHTML = `
      <div class="grid grid-3">
        ${statTile({ label: 'Open orders', value: num(open.length), tone: 'accent' })}
        ${statTile({ label: 'Committed spend', value: money(committed), tone: 'info',
                     sub: 'on orders not yet received' })}
        ${statTile({ label: 'Total orders', value: num(orders.length) })}
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h3>Purchase orders</h3></div>
        ${table([
          { label: 'Order', render: (r) => `<strong>${esc(r.po_no)}</strong>`, nowrap: true },
          { label: 'Supplier', render: (r) => esc(r.supplier_code) },
          { label: 'Status', render: (r) => badge(r.status, STATUS_TONE[r.status] || '') },
          { label: 'Lines', align: 'right', render: (r) => num(r.line_count) },
          { label: 'Value', align: 'right', render: (r) => money(r.total_cost) },
          { label: 'Raised', render: (r) => `<span class="faint">
              ${esc(String(r.created_at).slice(0, 10))}</span>`, nowrap: true },
          { label: 'Expected', render: (r) => r.expected_at
              ? esc(String(r.expected_at).slice(0, 10)) : '—', nowrap: true },
          { label: 'By', render: (r) => `<span class="muted">${esc(r.created_by_name)}</span>` },
        ], orders, {
          emptyMessage: 'No purchase orders yet — build one from Stock intelligence',
          rowAttrs: (r) => `data-po="${r.id}"`,
          onRowClick: true,
        })}
      </div>`;

    box.querySelectorAll('[data-po]').forEach((row) => {
      row.addEventListener('click', () => openOrder(Number(row.dataset.po)));
    });
  } catch (error) {
    box.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

async function openOrder(poId) {
  modal({ title: 'Purchase order', body: loading(), wide: true });
  try {
    const data = await api.get(`/api/purchasing/orders/${poId}`);
    document.querySelector('.modal-backdrop:last-child')?.remove();
    showOrder(data);
  } catch (error) {
    document.querySelector('.modal-backdrop:last-child')?.remove();
    toast(error.message, 'error');
  }
}

function showOrder(data) {
  const { po, lines } = data;
  const canEdit = session.can('purchasing.edit');
  const canReceive = session.can('purchasing.receive');
  const receivable = ['ordered', 'partial'].includes(po.status);

  const buttons = [
    '<button class="btn" data-close>Close</button>',
    canEdit && po.status === 'draft'
      ? '<button class="btn btn-danger" id="po-cancel">Cancel order</button>' : '',
    canEdit && po.status === 'draft'
      ? '<button class="btn btn-primary" id="po-send">Send to supplier</button>' : '',
    canReceive && receivable
      ? '<button class="btn btn-ok" id="po-receive">Receive delivery</button>' : '',
  ].filter(Boolean).join('');

  modal({
    title: `${po.po_no} — ${po.supplier_code}`,
    wide: true,
    body: `
      <div class="grid grid-4">
        ${statTile({ label: 'Status', value: badge(po.status, STATUS_TONE[po.status] || ''),
                     tone: po.status === 'received' ? 'ok' : 'accent' })}
        ${statTile({ label: 'Order value', value: money(po.total_cost) })}
        ${statTile({ label: 'Expected', value: po.expected_at
                     ? esc(String(po.expected_at).slice(0, 10)) : '—',
                     sub: `lead time ${num(po.lead_time_days)} days` })}
        ${statTile({ label: 'Raised by', value: esc(po.created_by_name),
                     sub: esc(String(po.created_at).slice(0, 16)) })}
      </div>
      ${po.note ? `<div class="alert alert-info" style="margin-top:14px">${esc(po.note)}</div>` : ''}
      <div class="card" style="margin-top:14px">
        ${table([
          { label: 'Item', render: (r) => `<strong>${esc(r.description)}</strong>
              <div class="faint" style="font-size:11.5px">${esc(r.sku)}</div>` },
          { label: 'On hand', align: 'right', render: (r) => num(r.stock_qty) },
          { label: 'Ordered', align: 'right', render: (r) => num(r.qty_ordered) },
          { label: 'Received', align: 'right', render: (r) => num(r.qty_received) },
          { label: 'Outstanding', align: 'right', render: (r) => {
              const left = Number(r.qty_ordered) - Number(r.qty_received);
              return left > 0 ? `<strong style="color:var(--warn)">${num(left)}</strong>` : '—';
            } },
          { label: 'Unit cost', align: 'right', render: (r) => money(r.unit_cost) },
          { label: 'Line total', align: 'right',
            render: (r) => money(Number(r.qty_ordered) * Number(r.unit_cost)) },
        ], lines)}
      </div>`,
    footer: buttons,
    onMount: (root, close) => {
      root.querySelector('#po-send')?.addEventListener('click', async () => {
        try {
          await api.post(`/api/purchasing/orders/${po.id}/send`);
          close(); toast('Order sent to supplier', 'ok'); load();
        } catch (error) { toast(error.message, 'error'); }
      });
      root.querySelector('#po-cancel')?.addEventListener('click', async () => {
        try {
          await api.post(`/api/purchasing/orders/${po.id}/cancel`);
          close(); toast('Order cancelled', 'ok'); load();
        } catch (error) { toast(error.message, 'error'); }
      });
      root.querySelector('#po-receive')?.addEventListener('click', () => {
        close(); openReceive(po, lines);
      });
    },
  });
}

function openReceive(po, lines) {
  const outstanding = lines.filter((l) => Number(l.qty_ordered) - Number(l.qty_received) > 0);

  modal({
    title: `Receive delivery — ${po.po_no}`,
    wide: true,
    body: `
      <p class="muted">Enter what actually arrived. Leave a line at zero if it did not come.</p>
      <div class="table-wrap"><table><thead><tr>
        <th>Item</th><th class="num">Outstanding</th>
        <th class="num">Receiving</th><th class="num">Unit cost</th>
      </tr></thead><tbody>
        ${outstanding.map((line) => {
          const left = Number(line.qty_ordered) - Number(line.qty_received);
          return `<tr>
            <td><strong>${esc(line.description)}</strong>
              <div class="faint" style="font-size:11.5px">${esc(line.sku)}</div></td>
            <td class="num">${num(left)}</td>
            <td class="num"><input type="number" min="0" max="${left}" step="1"
                  value="${left}" data-recv="${line.id}" style="width:90px"></td>
            <td class="num"><input type="number" min="0" step="0.01"
                  value="${Number(line.unit_cost).toFixed(2)}" data-cost="${line.id}"
                  style="width:100px"></td>
          </tr>`;
        }).join('')}
      </tbody></table></div>
      <label class="field" style="margin-top:14px"><span>Delivery note / invoice reference</span>
        <input id="recv-note"></label>
      <div id="recv-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-ok" id="recv-save">Book in delivery</button>`,
    onMount: (root, close) => {
      root.querySelector('#recv-save').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        const errorBox = root.querySelector('#recv-error');
        errorBox.hidden = true;

        const payload = {
          note: root.querySelector('#recv-note').value,
          lines: [...root.querySelectorAll('[data-recv]')].map((input) => ({
            po_line_id: Number(input.dataset.recv),
            qty_received: Number(input.value) || 0,
            unit_cost: Number(
              root.querySelector(`[data-cost="${input.dataset.recv}"]`).value) || 0,
          })).filter((line) => line.qty_received > 0),
        };

        if (!payload.lines.length) {
          errorBox.textContent = 'Enter at least one quantity to receive.';
          errorBox.hidden = false;
          button.disabled = false;
          return;
        }

        try {
          const result = await api.post(`/api/purchasing/orders/${po.id}/receive`, payload);
          close();
          toast(`Delivery booked in — order is now ${result.po.status}`, 'ok');
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
