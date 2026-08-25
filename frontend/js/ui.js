// Shared rendering helpers: formatting, escaping, toasts, modals and mini charts.

import { session } from './api.js';

export const el = (id) => document.getElementById(id);

/** Escape untrusted text before it goes anywhere near innerHTML. */
export function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function money(value, withSymbol = true) {
  const number = Number(value || 0);
  const symbol = withSymbol ? (session.settings.currency_symbol || '₱') : '';
  return symbol + number.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function num(value, decimals = 0) {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function pct(value, decimals = 1) {
  return `${Number(value || 0).toFixed(decimals)}%`;
}

export function dateOnly(value) {
  return value ? String(value).slice(0, 10) : '';
}

export function today() {
  return new Date().toISOString().slice(0, 10);
}

export function daysAgo(days) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

export function toast(message, kind = 'info', ms = 4200) {
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  node.textContent = message;
  el('toasts').appendChild(node);
  setTimeout(() => node.remove(), ms);
}

/**
 * Open a modal. `body` is trusted HTML built by the caller; any interpolated
 * server data must already have gone through esc().
 */
export function modal({ title, body, footer = '', wide = false, onMount }) {
  const root = el('modal-root');
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `
    <div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>${esc(title)}</h3>
        <button class="close-x" data-close aria-label="Close">&times;</button>
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
    </div>`;

  const close = () => {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (event) => { if (event.key === 'Escape') close(); };

  backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop || event.target.hasAttribute('data-close')) close();
  });
  document.addEventListener('keydown', onKey);

  root.appendChild(backdrop);
  if (onMount) onMount(backdrop, close);
  return close;
}

export function confirmDialog(message, { title = 'Please confirm', danger = false } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const close = modal({
      title,
      body: `<p>${esc(message)}</p>`,
      footer: `
        <button class="btn" data-no>Cancel</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-yes>Confirm</button>`,
      onMount: (root, dismiss) => {
        root.querySelector('[data-yes]').addEventListener('click', () => {
          settled = true;
          dismiss();
          resolve(true);
        });
        root.querySelector('[data-no]').addEventListener('click', () => {
          settled = true;
          dismiss();
          resolve(false);
        });
        root.addEventListener('click', (event) => {
          if (event.target === root) setTimeout(() => { if (!settled) resolve(false); }, 0);
        });
      },
    });
    void close;
  });
}

export const loading = (message = 'Loading…') => `<div class="loading">${esc(message)}</div>`;

export function empty(message, icon = '📭') {
  return `<div class="empty"><span class="empty-icon">${icon}</span>${esc(message)}</div>`;
}

export function statTile({ label, value, sub = '', tone = '' }) {
  return `
    <div class="stat ${tone}">
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value">${value}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>`;
}

export function badge(text, kind = '') {
  return `<span class="badge ${kind ? `badge-${kind}` : ''}">${esc(text)}</span>`;
}

export function movementBadge(movement) {
  return badge(movement || 'n/a', movement || '');
}

export function urgencyBar(score) {
  const value = Math.max(0, Math.min(100, Number(score) || 0));
  const colour = value >= 60 ? 'var(--danger)' : value >= 30 ? 'var(--warn)' : 'var(--ok)';
  return `
    <div style="display:flex;align-items:center;gap:8px">
      <div class="urgency-bar"><div class="urgency-fill"
        style="width:${value}%;background:${colour}"></div></div>
      <span class="faint" style="font-size:11.5px">${value.toFixed(0)}</span>
    </div>`;
}

/** Table renderer. `columns[].render` returns trusted HTML; plain keys are escaped. */
export function table(columns, rows, options = {}) {
  if (!rows.length) return empty(options.emptyMessage || 'Nothing to show yet');

  const head = columns
    .map((column) => `<th class="${column.align === 'right' ? 'num' : ''}">${esc(column.label)}</th>`)
    .join('');

  const body = rows.map((row, index) => {
    const cells = columns.map((column) => {
      const content = column.render ? column.render(row, index) : esc(row[column.key]);
      const classes = [column.align === 'right' ? 'num' : '', column.nowrap ? 'nowrap' : '']
        .filter(Boolean).join(' ');
      return `<td class="${classes}">${content}</td>`;
    }).join('');
    const attrs = options.rowAttrs ? options.rowAttrs(row, index) : '';
    return `<tr class="${options.onRowClick ? 'clickable' : ''}" ${attrs}>${cells}</tr>`;
  }).join('');

  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead>
          <tbody>${body}</tbody></table></div>`;
}

/** Inline SVG bar chart — no chart library, no external requests. */
export function barChart(points, { height = 180, valueKey = 'value', labelKey = 'label',
                                   colour = 'var(--accent)', format = num } = {}) {
  if (!points.length) return empty('No data for this period');

  // A wide coordinate space with the default (uniform) preserveAspectRatio keeps
  // the axis labels legible; stretching the viewBox would smear the text.
  const width = 900;
  const padBottom = 22;
  const values = points.map((point) => Number(point[valueKey]) || 0);
  const max = Math.max(...values, 1);
  const slot = width / points.length;
  const barWidth = Math.min(slot * 0.7, 48);

  const bars = points.map((point, index) => {
    const value = Number(point[valueKey]) || 0;
    const barHeight = (value / max) * (height - padBottom - 6);
    const x = index * slot + (slot - barWidth) / 2;
    const y = height - padBottom - barHeight;
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}"
              width="${barWidth.toFixed(1)}" height="${Math.max(barHeight, 1).toFixed(1)}"
              rx="2" fill="${colour}" opacity="0.9">
              <title>${esc(point[labelKey])}: ${esc(format(value))}</title>
            </rect>`;
  }).join('');

  const step = Math.max(1, Math.ceil(points.length / 8));
  const labels = points.map((point, index) => {
    if (index % step !== 0) return '';
    const x = index * slot + slot / 2;
    return `<text x="${x.toFixed(1)}" y="${height - 7}" font-size="13"
              fill="var(--text-faint)" text-anchor="middle">${esc(
                String(point[labelKey]).slice(-5))}</text>`;
  }).join('');

  const baseline = `<line x1="0" y1="${height - padBottom}" x2="${width}"
    y2="${height - padBottom}" stroke="var(--border)" stroke-width="1"/>`;

  return `<svg class="chart" viewBox="0 0 ${width} ${height}"
            role="img" aria-label="Bar chart">${baseline}${bars}${labels}</svg>`;
}

export function debounce(fn, ms = 250) {
  let handle;
  return (...args) => {
    clearTimeout(handle);
    handle = setTimeout(() => fn(...args), ms);
  };
}
