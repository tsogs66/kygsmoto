// The till: search parts, add labour, tender, print.

import { api, session } from '../api.js';
import {
  confirmDialog, debounce, empty, esc, loading, modal, money, num, toast,
} from '../ui.js';

const cart = { lines: [], customer: '', plate: '', orderDiscount: 0 };
let services = [];
let mode = 'parts';

export async function render(root) {
  root.innerHTML = `
    <div class="page-head">
      <div>
        <h2>Point of Sale</h2>
        <p>Scan a barcode, or search by item code or description.</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-sm" id="pos-holds">Held sales</button>
        <button class="btn btn-sm" id="pos-drawer">Cash drawer</button>
      </div>
    </div>

    <div class="pos-layout">
      <div class="card">
        <div class="tab-row">
          <button class="tab active" data-mode="parts">Parts</button>
          <button class="tab" data-mode="services">Labour &amp; services</button>
        </div>
        <div class="pos-search">
          <input id="pos-search" placeholder="Scan barcode or type item code / description…"
                 autocomplete="off">
        </div>
        <div class="pos-results" id="pos-results"></div>
      </div>

      <div class="card cart-panel">
        <div class="card-head"><h3>Current sale</h3><span id="cart-count" class="hint"></span></div>
        <div class="cart-lines" id="cart-lines"></div>
        <div class="cart-totals" id="cart-totals"></div>
        <div style="display:grid;gap:8px;margin-top:14px">
          <button class="btn btn-primary btn-lg" id="cart-pay" disabled>Take payment</button>
          <div style="display:flex;gap:8px">
            <button class="btn btn-sm" id="cart-hold" style="flex:1" disabled>Hold</button>
            <button class="btn btn-sm" id="cart-clear" style="flex:1" disabled>Clear</button>
          </div>
        </div>
      </div>
    </div>`;

  const search = document.getElementById('pos-search');
  search.addEventListener('input', debounce(() => runSearch(search.value), 220));
  search.addEventListener('keydown', async (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    // A barcode scanner types fast then sends Enter: try an exact match first.
    const code = search.value.trim();
    if (!code) return;
    try {
      const item = await api.get('/api/items/lookup', { code });
      addItem(item);
      search.value = '';
      runSearch('');
    } catch {
      runSearch(code);
    }
  });

  root.querySelectorAll('[data-mode]').forEach((tab) => {
    tab.addEventListener('click', () => {
      mode = tab.dataset.mode;
      root.querySelectorAll('[data-mode]').forEach((t) => t.classList.toggle(
        'active', t === tab));
      // A term typed against parts rarely matches a service name, so start the
      // other list clean rather than showing a puzzling empty result.
      const box = document.getElementById('pos-search');
      box.value = '';
      box.placeholder = mode === 'parts'
        ? 'Scan barcode or type item code / description…'
        : 'Search services…';
      box.focus();
      runSearch('');
    });
  });

  document.getElementById('cart-pay').addEventListener('click', openPayment);
  document.getElementById('cart-clear').addEventListener('click', async () => {
    if (await confirmDialog('Clear every line from this sale?', { danger: true })) {
      cart.lines = [];
      cart.orderDiscount = 0;
      drawCart();
    }
  });
  document.getElementById('cart-hold').addEventListener('click', holdSale);
  document.getElementById('pos-holds').addEventListener('click', openHolds);
  document.getElementById('pos-drawer').addEventListener('click', openDrawer);

  services = (await api.get('/api/services')).services;
  drawCart();
  runSearch('');
  search.focus();
}

async function runSearch(term) {
  const box = document.getElementById('pos-results');
  if (!box) return;

  if (mode === 'services') {
    const matches = services.filter((service) =>
      service.name.toLowerCase().includes(term.toLowerCase()));
    box.innerHTML = matches.length
      ? matches.map((service) => `
          <div class="result-row" data-service="${service.id}">
            <div class="result-main">
              <div class="result-desc">${esc(service.name)}</div>
              <div class="result-meta">${esc(service.code)} · labour</div>
            </div>
            <div class="result-price">${money(service.fee)}</div>
          </div>`).join('')
      : empty('No matching service');

    box.querySelectorAll('[data-service]').forEach((row) => {
      row.addEventListener('click', () => {
        const service = services.find((s) => s.id === Number(row.dataset.service));
        addService(service);
      });
    });
    return;
  }

  box.innerHTML = loading('Searching…');
  try {
    const { items } = await api.get('/api/items', { q: term, limit: 40, status: 'active' });
    box.innerHTML = items.length
      ? items.map((item) => `
          <div class="result-row ${item.stock_qty <= 0 ? 'out' : ''}" data-item="${item.id}">
            <div class="result-main">
              <div class="result-desc">${esc(item.description)}</div>
              <div class="result-meta">
                ${esc(item.sku)} · ${esc(item.category || '')} ·
                ${item.stock_qty <= 0
                  ? '<span style="color:var(--danger)">out of stock</span>'
                  : `${num(item.stock_qty)} on hand`}
              </div>
            </div>
            <div class="result-price">${money(item.retail_price)}</div>
          </div>`).join('')
      : empty(term ? 'No item matches that search' : 'Start typing to find a part', '🔍');

    box.querySelectorAll('[data-item]').forEach((row) => {
      row.addEventListener('click', () => {
        const item = items.find((i) => i.id === Number(row.dataset.item));
        addItem(item);
      });
    });
  } catch (error) {
    box.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function addItem(item) {
  const existing = cart.lines.find((line) => line.type === 'item' && line.id === item.id);
  const inCart = existing ? existing.qty : 0;

  if (inCart + 1 > item.stock_qty) {
    toast(`Only ${num(item.stock_qty)} of ${item.description} in stock.`, 'warn');
    if (item.stock_qty <= 0) return;
  }

  if (existing) existing.qty += 1;
  else cart.lines.push({
    type: 'item', id: item.id, sku: item.sku, description: item.description,
    qty: 1, price: Number(item.retail_price), cost: Number(item.unit_cost),
    stock: Number(item.stock_qty), discount: 0,
  });

  drawCart();
}

function addService(service) {
  if (!service) return;
  const existing = cart.lines.find((line) => line.type === 'service' && line.id === service.id);
  if (existing) existing.qty += 1;
  else cart.lines.push({
    type: 'service', id: service.id, sku: service.code, description: service.name,
    qty: 1, price: Number(service.fee), cost: 0, stock: null, discount: 0,
  });
  drawCart();
}

function lineTotal(line) {
  return line.qty * line.price - line.discount;
}

function cartTotals() {
  const subtotal = cart.lines.reduce((sum, line) => sum + lineTotal(line), 0);
  const parts = cart.lines.filter((l) => l.type === 'item')
    .reduce((sum, line) => sum + lineTotal(line), 0);
  const labour = subtotal - parts;
  const total = Math.max(subtotal - cart.orderDiscount, 0);
  return { subtotal, parts, labour, total };
}

function drawCart() {
  const box = document.getElementById('cart-lines');
  if (!box) return;

  box.innerHTML = cart.lines.length
    ? cart.lines.map((line, index) => `
        <div class="cart-line">
          <div>
            <div class="cart-line-desc">${esc(line.description)}</div>
            <div class="cart-line-sub">
              ${esc(line.sku)} · ${money(line.price)} each
              ${line.type === 'service' ? '· labour' : ''}
            </div>
          </div>
          <div class="cart-line-total">${money(lineTotal(line))}</div>
          <div class="cart-qty">
            <button class="qty-btn" data-dec="${index}" aria-label="Less">−</button>
            <input type="number" min="0" step="1" value="${line.qty}" data-qty="${index}">
            <button class="qty-btn" data-inc="${index}" aria-label="More">+</button>
          </div>
          <div style="text-align:right">
            <button class="qty-btn" data-del="${index}" aria-label="Remove">×</button>
          </div>
        </div>`).join('')
    : empty('No lines yet — scan or search to add parts', '🛒');

  const totals = cartTotals();
  document.getElementById('cart-totals').innerHTML = `
    <div class="total-row"><span class="muted">Parts</span>
      <span class="num">${money(totals.parts)}</span></div>
    <div class="total-row"><span class="muted">Labour</span>
      <span class="num">${money(totals.labour)}</span></div>
    ${cart.orderDiscount > 0 ? `<div class="total-row"><span class="muted">Discount</span>
      <span class="num" style="color:var(--warn)">−${money(cart.orderDiscount)}</span></div>` : ''}
    <div class="total-row grand"><span>Total</span>
      <span class="num">${money(totals.total)}</span></div>`;

  document.getElementById('cart-count').textContent =
    cart.lines.length ? `${cart.lines.length} line${cart.lines.length > 1 ? 's' : ''}` : '';

  for (const id of ['cart-pay', 'cart-hold', 'cart-clear']) {
    document.getElementById(id).disabled = cart.lines.length === 0;
  }

  box.querySelectorAll('[data-inc]').forEach((button) => button.addEventListener('click', () => {
    const line = cart.lines[Number(button.dataset.inc)];
    if (line.stock !== null && line.qty + 1 > line.stock) {
      toast(`Only ${num(line.stock)} in stock.`, 'warn');
      return;
    }
    line.qty += 1;
    drawCart();
  }));
  box.querySelectorAll('[data-dec]').forEach((button) => button.addEventListener('click', () => {
    const line = cart.lines[Number(button.dataset.dec)];
    line.qty = Math.max(1, line.qty - 1);
    drawCart();
  }));
  box.querySelectorAll('[data-del]').forEach((button) => button.addEventListener('click', () => {
    cart.lines.splice(Number(button.dataset.del), 1);
    drawCart();
  }));
  box.querySelectorAll('[data-qty]').forEach((input) => input.addEventListener('change', () => {
    const line = cart.lines[Number(input.dataset.qty)];
    const value = Math.max(0, Number(input.value) || 0);
    if (value === 0) cart.lines.splice(Number(input.dataset.qty), 1);
    else if (line.stock !== null && value > line.stock) {
      toast(`Only ${num(line.stock)} in stock.`, 'warn');
      line.qty = line.stock;
    } else line.qty = value;
    drawCart();
  }));
}

function openPayment() {
  const totals = cartTotals();
  const canDiscount = session.can('pos.discount');

  modal({
    title: 'Take payment',
    body: `
      <div class="grid grid-2">
        <label class="field"><span>Customer name (optional)</span>
          <input id="pay-customer" value="${esc(cart.customer)}"></label>
        <label class="field"><span>Plate number (optional)</span>
          <input id="pay-plate" value="${esc(cart.plate)}"></label>
      </div>
      ${canDiscount ? `<label class="field"><span>Order discount</span>
        <input id="pay-discount" type="number" min="0" step="0.01"
               value="${cart.orderDiscount}"></label>` : ''}
      <label class="field"><span>Payment method</span>
        <select id="pay-method">
          <option value="CASH">Cash</option>
          <option value="GCASH">GCash</option>
          <option value="BANK">Bank transfer</option>
          <option value="CARD">Card</option>
        </select></label>
      <label class="field" id="pay-ref-field" hidden><span>Reference number</span>
        <input id="pay-reference" placeholder="Transaction reference"></label>
      <label class="field"><span>Amount tendered</span>
        <input id="pay-tendered" type="number" min="0" step="0.01"
               value="${totals.total.toFixed(2)}"></label>
      <div class="card" style="background:var(--surface-2)">
        <div class="total-row grand" style="border:0;margin:0;padding:0">
          <span>Due</span><span class="num" id="pay-due">${money(totals.total)}</span></div>
        <div class="total-row"><span class="muted">Change</span>
          <span class="num" id="pay-change">${money(0)}</span></div>
      </div>
      <div id="pay-error" class="alert alert-error" hidden style="margin-top:12px"></div>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-ok btn-lg" id="pay-confirm">Complete sale</button>`,
    onMount: (root, close) => {
      const method = root.querySelector('#pay-method');
      const tendered = root.querySelector('#pay-tendered');
      const discount = root.querySelector('#pay-discount');
      const refField = root.querySelector('#pay-ref-field');

      const recalc = () => {
        const off = discount ? Math.max(0, Number(discount.value) || 0) : 0;
        const due = Math.max(totals.subtotal - off, 0);
        root.querySelector('#pay-due').textContent = money(due);
        const change = Math.max((Number(tendered.value) || 0) - due, 0);
        root.querySelector('#pay-change').textContent = money(change);
        return due;
      };

      method.addEventListener('change', () => {
        refField.hidden = method.value === 'CASH';
      });
      tendered.addEventListener('input', recalc);
      if (discount) discount.addEventListener('input', recalc);

      root.querySelector('#pay-confirm').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        const due = recalc();
        const errorBox = root.querySelector('#pay-error');
        errorBox.hidden = true;

        const tenderedValue = Number(tendered.value) || 0;
        if (method.value === 'CASH' && tenderedValue + 0.005 < due) {
          errorBox.textContent = `Cash tendered ${money(tenderedValue)} is less than ${money(due)}.`;
          errorBox.hidden = false;
          button.disabled = false;
          return;
        }

        try {
          const payload = {
            lines: cart.lines.map((line) => ({
              line_type: line.type === 'item' ? 'item' : 'service',
              item_id: line.type === 'item' ? line.id : null,
              service_id: line.type === 'service' ? line.id : null,
              qty: line.qty,
              discount: line.discount,
            })),
            payments: [{
              method: method.value,
              amount: due,
              reference: root.querySelector('#pay-reference').value || '',
            }],
            customer_name: root.querySelector('#pay-customer').value,
            plate_no: root.querySelector('#pay-plate').value,
            order_discount: discount ? Math.max(0, Number(discount.value) || 0) : 0,
            amount_tendered: method.value === 'CASH' ? tenderedValue : due,
          };
          const sale = await api.post('/api/pos/sales', payload);
          close();
          cart.lines = [];
          cart.orderDiscount = 0;
          cart.customer = '';
          cart.plate = '';
          drawCart();
          toast(`Sale ${sale.sale.receipt_no} completed`, 'ok');
          showReceipt(sale);
          document.getElementById('pos-search')?.focus();
        } catch (error) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
          button.disabled = false;
        }
      });
    },
  });
}

export function showReceipt(payload) {
  const { sale, lines, payments, shop } = payload;
  const line = (label, value) =>
    `<div class="receipt-row"><span>${esc(label)}</span><span>${esc(value)}</span></div>`;

  modal({
    title: `Receipt ${sale.receipt_no}`,
    body: `
      <div class="receipt" id="receipt-print">
        <div class="receipt-center">
          <strong>${esc(shop.name || 'KYGS')}</strong><br>
          ${shop.address ? `${esc(shop.address)}<br>` : ''}
          ${shop.phone ? `${esc(shop.phone)}<br>` : ''}
        </div>
        <hr>
        ${line('Receipt', sale.receipt_no)}
        ${line('Date', String(sale.ts).slice(0, 16))}
        ${line('Cashier', sale.cashier)}
        ${sale.customer_name ? line('Customer', sale.customer_name) : ''}
        ${sale.plate_no ? line('Plate', sale.plate_no) : ''}
        <hr>
        ${lines.map((item) => `
          <div style="margin-bottom:4px">
            <div>${esc(item.description)}</div>
            <div class="receipt-row">
              <span>&nbsp;&nbsp;${num(item.qty, 0)} × ${money(item.unit_price, false)}</span>
              <span>${money(item.total, false)}</span>
            </div>
          </div>`).join('')}
        <hr>
        ${line('Subtotal', money(sale.subtotal, false))}
        ${Number(sale.discount) > 0 ? line('Discount', `-${money(sale.discount, false)}`) : ''}
        <div class="receipt-row" style="font-weight:700;font-size:14px">
          <span>TOTAL</span><span>${esc(money(sale.total, false))}</span></div>
        ${payments.map((payment) => line(payment.method, money(payment.amount, false))).join('')}
        ${line('Tendered', money(sale.amount_tendered, false))}
        ${line('Change', money(sale.change_due, false))}
        <hr>
        <div class="receipt-center">${esc(shop.footer || '')}</div>
      </div>`,
    footer: `<button class="btn" data-close>Close</button>
             <button class="btn btn-primary" id="receipt-print-btn">Print</button>`,
    onMount: (root) => {
      root.querySelector('#receipt-print-btn').addEventListener('click', () => window.print());
    },
  });
}

async function holdSale() {
  const label = cart.customer || `Hold ${new Date().toLocaleTimeString()}`;
  await api.post('/api/pos/holds', { label, payload: { lines: cart.lines } });
  cart.lines = [];
  cart.orderDiscount = 0;
  drawCart();
  toast('Sale held', 'ok');
}

async function openHolds() {
  const { holds } = await api.get('/api/pos/holds');
  modal({
    title: 'Held sales',
    body: holds.length
      ? `<div class="table-wrap"><table><thead><tr>
           <th>Label</th><th>Cashier</th><th class="num">Lines</th><th></th></tr></thead><tbody>
           ${holds.map((hold) => `<tr>
             <td>${esc(hold.label)}</td>
             <td class="muted">${esc(hold.username)}</td>
             <td class="num">${hold.payload.lines?.length || 0}</td>
             <td class="nowrap">
               <button class="btn btn-sm" data-resume="${hold.id}">Resume</button>
               <button class="btn btn-sm btn-danger" data-drop="${hold.id}">Delete</button>
             </td></tr>`).join('')}
         </tbody></table></div>`
      : empty('No held sales'),
    onMount: (root, close) => {
      root.querySelectorAll('[data-resume]').forEach((button) => {
        button.addEventListener('click', () => {
          const hold = holds.find((h) => h.id === Number(button.dataset.resume));
          cart.lines = hold.payload.lines || [];
          cart.customer = hold.label;
          api.del(`/api/pos/holds/${hold.id}`);
          drawCart();
          close();
          toast('Sale resumed', 'ok');
        });
      });
      root.querySelectorAll('[data-drop]').forEach((button) => {
        button.addEventListener('click', async () => {
          await api.del(`/api/pos/holds/${button.dataset.drop}`);
          close();
          openHolds();
        });
      });
    },
  });
}

async function openDrawer() {
  const { drawer } = await api.get('/api/pos/drawer');

  if (!drawer) {
    modal({
      title: 'Open the cash drawer',
      body: `<label class="field"><span>Opening cash float</span>
               <input id="drawer-open-amount" type="number" min="0" step="0.01" value="0"></label>`,
      footer: `<button class="btn" data-close>Cancel</button>
               <button class="btn btn-primary" id="drawer-open-btn">Open drawer</button>`,
      onMount: (root, close) => {
        root.querySelector('#drawer-open-btn').addEventListener('click', async () => {
          await api.post('/api/pos/drawer/open', {
            opening_cash: Number(root.querySelector('#drawer-open-amount').value) || 0,
          });
          close();
          toast('Drawer opened', 'ok');
        });
      },
    });
    return;
  }

  modal({
    title: 'Close the cash drawer',
    body: `
      <dl class="kv">
        <dt>Opened by</dt><dd>${esc(drawer.opened_by_name)}</dd>
        <dt>Opened at</dt><dd>${esc(String(drawer.opened_at).slice(0, 16))}</dd>
        <dt>Opening float</dt><dd>${money(drawer.opening_cash)}</dd>
        <dt>Cash sales</dt><dd>${money(drawer.cash_sales)}</dd>
        <dt>Change given</dt><dd>−${money(drawer.change_given)}</dd>
        <dt class="strong">Expected in drawer</dt>
        <dd class="strong">${money(drawer.expected_cash)}</dd>
      </dl>
      <label class="field" style="margin-top:16px"><span>Counted cash</span>
        <input id="drawer-count" type="number" min="0" step="0.01"
               value="${Number(drawer.expected_cash).toFixed(2)}"></label>
      <label class="field"><span>Note</span><input id="drawer-note"></label>`,
    footer: `<button class="btn" data-close>Cancel</button>
             <button class="btn btn-primary" id="drawer-close-btn">Close drawer</button>`,
    onMount: (root, close) => {
      root.querySelector('#drawer-close-btn').addEventListener('click', async () => {
        const result = await api.post('/api/pos/drawer/close', {
          counted_cash: Number(root.querySelector('#drawer-count').value) || 0,
          note: root.querySelector('#drawer-note').value,
        });
        close();
        const tone = result.status === 'balanced' ? 'ok' : 'warn';
        toast(`Drawer ${result.status} — variance ${money(result.variance)}`, tone);
      });
    },
  });
}
