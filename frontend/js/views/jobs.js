// Job queue: bikes in the shop, what stage they are at, and taking payment.

import { api, session } from '../api.js';
import {
  badge, empty, esc, loading, modal, money, num, statTile, table, toast,
} from '../ui.js';

const STATUS_LABEL = {
  queued: 'Waiting', in_progress: 'In progress', ready: 'Ready for release',
  completed: 'Completed', cancelled: 'Cancelled',
};
const STATUS_TONE = {
  queued: 'warn', in_progress: 'medium', ready: 'ok',
  completed: 'c', cancelled: 'danger',
};
const NEXT_STATUS = { queued: 'in_progress', in_progress: 'ready' };
const NEXT_LABEL = { queued: 'Start work', in_progress: 'Mark ready' };

let onQueueChanged = () => {};

export function setChangeHandler(fn) {
  onQueueChanged = fn;
}

export async function render(root) {
  root.innerHTML = `
    <div class="filters" style="justify-content:space-between">
      <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
        <label class="field" style="margin:0"><span>Show</span>
          <select id="jq-filter">
            <option value="open">Open jobs</option>
            <option value="queued">Waiting</option>
            <option value="in_progress">In progress</option>
            <option value="ready">Ready for release</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select></label>
        <label class="field grow" style="margin:0"><span>Search</span>
          <input id="jq-search" placeholder="Job number, customer, plate or model"></label>
      </div>
      <button class="btn btn-primary" id="jq-new">New job ticket</button>
    </div>
    <div id="jq-body">${loading()}</div>`;

  document.getElementById('jq-filter').addEventListener('change', load);
  document.getElementById('jq-search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') load();
  });
  document.getElementById('jq-new').addEventListener('click', () => openEditor());
  load();
}

async function load() {
  const box = document.getElementById('jq-body');
  if (!box) return;
  const filter = document.getElementById('jq-filter').value;
  const q = document.getElementById('jq-search').value.trim();
  box.innerHTML = loading();

  try {
    const [board, list] = await Promise.all([
      api.get('/api/pos/jobs/board'),
      api.get('/api/pos/jobs', { status: filter, q, limit: 200 }),
    ]);
    onQueueChanged(board.open_total);

    box.innerHTML = `
      <div class="grid grid-4">
        ${statTile({ label: 'Waiting', value: num(board.counts.queued),
                     tone: board.counts.queued > 0 ? 'warn' : '' })}
        ${statTile({ label: 'In progress', value: num(board.counts.in_progress),
                     tone: 'info' })}
        ${statTile({ label: 'Ready for release', value: num(board.counts.ready),
                     tone: board.counts.ready > 0 ? 'ok' : '' })}
        ${statTile({ label: 'Value in the shop', value: money(board.open_value),
                     tone: 'accent', sub: `${num(board.open_total)} open job(s)` })}
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h3>${esc(STATUS_LABEL[filter] || 'Open jobs')}</h3>
          <span class="hint">urgent first, then longest waiting</span></div>
        ${table([
          { label: 'Job', nowrap: true, render: (r) => `<strong>${esc(r.job_no)}</strong>
              ${r.priority === 'urgent' ? ` ${badge('urgent', 'danger')}` : ''}` },
          { label: 'Customer', render: (r) => `${esc(r.customer_name || '—')}
              <div class="faint" style="font-size:11.5px">
                ${esc(r.plate_no || '')} ${esc(r.motorcycle || '')}</div>` },
          { label: 'Complaint', render: (r) =>
              `<span class="faint">${esc((r.complaint || '').slice(0, 46))}</span>` },
          { label: 'Status', render: (r) =>
              badge(STATUS_LABEL[r.status] || r.status, STATUS_TONE[r.status] || '') },
          { label: 'Mechanic', render: (r) =>
              `<span class="muted">${esc(r.assigned_to_name || 'unassigned')}</span>` },
          { label: 'Lines', align: 'right', render: (r) => num(r.line_count) },
          { label: 'Value', align: 'right', render: (r) => money(r.total) },
          { label: 'Waiting', align: 'right', render: (r) => r.hours_open === undefined
              ? '' : `${num(r.hours_open)}h` },
        ], list.jobs, {
          emptyMessage: q ? 'No job matches that search' : 'No jobs here',
          rowAttrs: (r) => `data-job="${r.id}"`,
          onRowClick: true,
        })}
      </div>`;

    box.querySelectorAll('[data-job]').forEach((row) => {
      row.addEventListener('click', () => openJob(Number(row.dataset.job)));
    });
  } catch (error) {
    box.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

async function openJob(jobId) {
  try {
    const data = await api.get(`/api/pos/jobs/${jobId}`);
    showJob(data);
  } catch (error) {
    toast(error.message, 'error');
  }
}

function showJob(data) {
  const { job, lines, totals } = data;
  const open = ['queued', 'in_progress', 'ready'].includes(job.status);
  const next = NEXT_STATUS[job.status];

  const buttons = [
    '<button class="btn" data-close>Close</button>',
    open ? '<button class="btn btn-danger" id="j-cancel">Cancel job</button>' : '',
    open ? '<button class="btn" id="j-add">Add work</button>' : '',
    next ? `<button class="btn" id="j-next">${NEXT_LABEL[job.status]}</button>` : '',
    open ? '<button class="btn btn-ok" id="j-pay">Take payment</button>' : '',
  ].filter(Boolean).join('');

  modal({
    title: `${job.job_no} — ${job.customer_name || 'Walk-in'}`,
    wide: true,
    body: `
      <div class="grid grid-4">
        ${statTile({ label: 'Status', value: badge(STATUS_LABEL[job.status] || job.status,
                                                   STATUS_TONE[job.status] || ''),
                     tone: job.status === 'ready' ? 'ok' : 'accent' })}
        ${statTile({ label: 'Motorcycle', value: esc(job.motorcycle || '—'),
                     sub: esc(job.plate_no || 'no plate') })}
        ${statTile({ label: 'Total so far', value: money(totals.total),
                     sub: `parts ${money(totals.parts)} · labour ${money(totals.labour)}` })}
        ${statTile({ label: 'Mechanic', value: esc(job.assigned_to_name || 'unassigned'),
                     sub: `opened by ${esc(job.created_by_name)}` })}
      </div>

      ${job.complaint ? `<div class="alert alert-info" style="margin-top:14px">
        <strong>Reported:</strong> ${esc(job.complaint)}</div>` : ''}
      ${totals.short_lines > 0 ? `<div class="alert alert-warn">
        ${num(totals.short_lines)} line(s) need more stock than is on the shelf —
        payment will be refused until stock is received or the line is reduced.</div>` : ''}
      ${job.status === 'cancelled' ? `<div class="alert alert-error">
        Cancelled: ${esc(job.cancel_reason)}</div>` : ''}
      ${job.receipt_no ? `<div class="alert alert-info">
        Paid on receipt <strong>${esc(job.receipt_no)}</strong></div>` : ''}

      <div class="card" style="margin-top:14px">
        <div class="card-head"><h3>Work on this job</h3></div>
        ${table([
          { label: 'Type', render: (r) => badge(r.line_type === 'item' ? 'part' : 'labour',
                                                r.line_type === 'item' ? 'b' : 'medium') },
          { label: 'Description', render: (r) => `${esc(r.description)}
              ${r.short ? ' <span class="badge badge-danger">short</span>' : ''}
              <div class="faint" style="font-size:11.5px">${esc(r.sku || '')}</div>` },
          { label: 'Qty', align: 'right', render: (r) => num(r.qty) },
          { label: 'Price', align: 'right', render: (r) => money(r.unit_price) },
          { label: 'Total', align: 'right', render: (r) => money(r.total) },
          { label: '', nowrap: true, render: (r) => open
              ? `<button class="btn btn-sm btn-danger" data-drop="${r.id}">Remove</button>` : '' },
        ], lines, { emptyMessage: 'No parts or labour recorded yet' })}
      </div>
      ${job.notes ? `<p class="faint" style="font-size:12.5px">${esc(job.notes)}</p>` : ''}`,
    footer: buttons,
    onMount: (root, close) => {
      root.querySelectorAll('[data-drop]').forEach((button) => {
        button.addEventListener('click', async () => {
          try {
            await api.del(`/api/pos/jobs/${job.id}/lines/${button.dataset.drop}`);
            close(); load(); openJob(job.id);
          } catch (error) { toast(error.message, 'error'); }
        });
      });

      root.querySelector('#j-next')?.addEventListener('click', async () => {
        try {
          await api.patch(`/api/pos/jobs/${job.id}`, { status: next });
          close(); load();
          toast(`${job.job_no} → ${STATUS_LABEL[next]}`, 'ok');
        } catch (error) { toast(error.message, 'error'); }
      });

      root.querySelector('#j-add')?.addEventListener('click', () => {
        close(); openAddWork(job.id);
      });

      root.querySelector('#j-cancel')?.addEventListener('click', async () => {
        close();
        const reason = await promptText('Why is this job being cancelled?', 'Cancel job');
        if (!reason) return;
        try {
          await api.post(`/api/pos/jobs/${job.id}/cancel`, { reason });
          load();
          toast(`${job.job_no} cancelled`, 'warn');
        } catch (error) { toast(error.message, 'error'); }
      });

      root.querySelector('#j-pay')?.addEventListener('click', () => {
        close(); openCheckout(job, totals);
      });
    },
  });
}

function promptText(question, title) {
  return new Promise((resolve) => {
    modal({
      title,
      body: `<label class="field"><span>${esc(question)}</span>
               <input id="pt-value" autofocus></label>`,
      footer: `<button class="btn" data-close>Back</button>
               <button class="btn btn-primary" id="pt-ok">Confirm</button>`,
      onMount: (root, close) => {
        const input = root.querySelector('#pt-value');
        const submit = () => { close(); resolve(input.value.trim()); };
        root.querySelector('#pt-ok').addEventListener('click', submit);
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
        root.querySelector('[data-close]').addEventListener('click', () => resolve(''));
        setTimeout(() => input.focus(), 50);
      },
    });
  });
}

async function openAddWork(jobId) {
  const services = (await api.get('/api/services')).services;

  modal({
    title: 'Add work to this job',
    wide: true,
    body: `
      <div class="tab-row">
        <button class="tab active" data-add="parts">Part</button>
        <button class="tab" data-add="services">Labour</button>
      </div>
      <input id="aw-search" placeholder="Search…" autocomplete="off">
      <div class="pos-results" id="aw-results" style="max-height:320px;margin-top:12px"></div>`,
    onMount: (root, close) => {
      let mode = 'parts';
      const results = root.querySelector('#aw-results');
      const search = root.querySelector('#aw-search');

      const add = async (payload) => {
        try {
          await api.post(`/api/pos/jobs/${jobId}/lines`, payload);
          close(); load(); openJob(jobId);
          toast('Added to job', 'ok');
        } catch (error) { toast(error.message, 'error'); }
      };

      const run = async () => {
        const term = search.value.trim();
        if (mode === 'services') {
          const matches = services.filter((s) =>
            s.name.toLowerCase().includes(term.toLowerCase()));
          results.innerHTML = matches.length ? matches.map((s) => `
            <div class="result-row" data-svc="${s.id}">
              <div class="result-main"><div class="result-desc">${esc(s.name)}</div>
                <div class="result-meta">${esc(s.code)} · labour</div></div>
              <div class="result-price">${money(s.fee)}</div></div>`).join('')
            : empty('No matching service');
          results.querySelectorAll('[data-svc]').forEach((row) => row.addEventListener(
            'click', () => add({ line_type: 'service',
                                 service_id: Number(row.dataset.svc), qty: 1 })));
          return;
        }

        const { items } = await api.get('/api/items', { q: term, limit: 30, status: 'active' });
        results.innerHTML = items.length ? items.map((i) => `
          <div class="result-row ${i.stock_qty <= 0 ? 'out' : ''}" data-item="${i.id}">
            <div class="result-main"><div class="result-desc">${esc(i.description)}</div>
              <div class="result-meta">${esc(i.sku)} · ${num(i.stock_qty)} on hand</div></div>
            <div class="result-price">${money(i.retail_price)}</div></div>`).join('')
          : empty('No matching part');
        results.querySelectorAll('[data-item]').forEach((row) => row.addEventListener(
          'click', () => add({ line_type: 'item',
                               item_id: Number(row.dataset.item), qty: 1 })));
      };

      root.querySelectorAll('[data-add]').forEach((tab) => tab.addEventListener('click', () => {
        mode = tab.dataset.add;
        root.querySelectorAll('[data-add]').forEach((t) => t.classList.toggle('active', t === tab));
        search.value = '';
        run();
      }));
      search.addEventListener('input', () => run());
      run();
    },
  });
}

function openCheckout(job, totals) {
  const canDiscount = session.can('pos.discount');

  modal({
    title: `Take payment — ${job.job_no}`,
    body: `
      <dl class="kv">
        <dt>Customer</dt><dd>${esc(job.customer_name || 'Walk-in')}</dd>
        <dt>Motorcycle</dt><dd>${esc(job.motorcycle || '—')} ${esc(job.plate_no || '')}</dd>
        <dt>Parts</dt><dd>${money(totals.parts)}</dd>
        <dt>Labour</dt><dd>${money(totals.labour)}</dd>
      </dl>
      ${canDiscount ? `<label class="field" style="margin-top:14px"><span>Order discount</span>
        <input id="jc-discount" type="number" min="0" step="0.01" value="0"></label>` : ''}
      <label class="field"><span>Payment method</span>
        <select id="jc-method">
          <option value="CASH">Cash</option><option value="GCASH">GCash</option>
          <option value="BANK">Bank transfer</option><option value="CARD">Card</option>
        </select></label>
      <label class="field"><span>Amount tendered</span>
        <input id="jc-tendered" type="number" min="0" step="0.01"
               value="${totals.total.toFixed(2)}"></label>
      <div class="card" style="background:var(--surface-2)">
        <div class="total-row grand" style="border:0;margin:0;padding:0">
          <span>Due</span><span class="num" id="jc-due">${money(totals.total)}</span></div>
        <div class="total-row"><span class="muted">Change</span>
          <span class="num" id="jc-change">${money(0)}</span></div>
      </div>
      <div id="jc-error" class="alert alert-error" hidden style="margin-top:12px"></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-ok btn-lg" id="jc-confirm">Complete job</button>`,
    onMount: (root, close) => {
      const tendered = root.querySelector('#jc-tendered');
      const discount = root.querySelector('#jc-discount');

      const recalc = () => {
        const off = discount ? Math.max(0, Number(discount.value) || 0) : 0;
        const due = Math.max(totals.total - off, 0);
        root.querySelector('#jc-due').textContent = money(due);
        root.querySelector('#jc-change').textContent =
          money(Math.max((Number(tendered.value) || 0) - due, 0));
        return due;
      };
      tendered.addEventListener('input', recalc);
      if (discount) discount.addEventListener('input', recalc);

      root.querySelector('#jc-confirm').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        const errorBox = root.querySelector('#jc-error');
        errorBox.hidden = true;
        const due = recalc();
        const method = root.querySelector('#jc-method').value;
        const tenderedValue = Number(tendered.value) || 0;

        if (method === 'CASH' && tenderedValue + 0.005 < due) {
          errorBox.textContent = `Cash tendered ${money(tenderedValue)} is less than ${money(due)}.`;
          errorBox.hidden = false;
          button.disabled = false;
          return;
        }

        try {
          const result = await api.post(`/api/pos/jobs/${job.id}/checkout`, {
            payments: [{ method, amount: due }],
            order_discount: discount ? Math.max(0, Number(discount.value) || 0) : 0,
            amount_tendered: method === 'CASH' ? tenderedValue : due,
          });
          close();
          load();
          toast(`${job.job_no} completed — ${result.sale.receipt_no}`, 'ok');
          const { showReceipt } = await import('./pos.js');
          showReceipt(result);
        } catch (error) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
          button.disabled = false;
        }
      });
    },
  });
}

/** Open the ticket editor. `seedLines` lets the till hand its cart over. */
export function openEditor(seedLines = []) {
  modal({
    title: 'New job ticket',
    wide: true,
    body: `
      <div class="grid grid-2">
        <label class="field"><span>Customer name</span><input id="j-customer"></label>
        <label class="field"><span>Contact number</span><input id="j-contact"></label>
        <label class="field"><span>Plate number</span><input id="j-plate"></label>
        <label class="field"><span>Motorcycle model</span>
          <input id="j-model" placeholder="e.g. Mio i125, NMAX, TMX"></label>
      </div>
      <label class="field"><span>Reported problem</span>
        <input id="j-complaint" placeholder="What did the customer bring it in for?"></label>
      <label class="field"><span>Notes</span><input id="j-notes"></label>
      <label class="field"><span>Priority</span>
        <select id="j-priority">
          <option value="normal">Normal</option>
          <option value="urgent">Urgent</option>
        </select></label>
      ${seedLines.length ? `<div class="alert alert-info">
        ${num(seedLines.length)} line(s) from the current sale will move onto this ticket.
        </div>` : ''}
      <div id="j-error" class="alert alert-error" hidden></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-primary" id="j-save">Open job</button>`,
    onMount: (root, close) => {
      root.querySelector('#j-save').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        const errorBox = root.querySelector('#j-error');
        errorBox.hidden = true;
        try {
          const created = await api.post('/api/pos/jobs', {
            customer_name: root.querySelector('#j-customer').value,
            contact: root.querySelector('#j-contact').value,
            plate_no: root.querySelector('#j-plate').value,
            motorcycle: root.querySelector('#j-model').value,
            complaint: root.querySelector('#j-complaint').value,
            notes: root.querySelector('#j-notes').value,
            priority: root.querySelector('#j-priority').value,
            lines: seedLines,
          });
          close();
          toast(`${created.job.job_no} opened`, 'ok');
          if (document.getElementById('jq-body')) load();
          else onQueueChanged();
        } catch (error) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
          button.disabled = false;
        }
      });
    },
  });
}

export async function pendingCount() {
  try {
    return (await api.get('/api/pos/jobs/board')).open_total;
  } catch {
    return 0;
  }
}


