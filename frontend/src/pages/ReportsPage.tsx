import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, peso } from '../api'
import type { InventoryReport, PeriodReport } from '../api'
import {
  CHART_ACCENT, CHART_COLORS, CHART_GRID, CHART_OK, CHART_SECONDARY, CHART_TICK,
  CHART_TOOLTIP,
} from '../chartTheme'

const COLORS = CHART_COLORS
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

type Metric = 'amount' | 'qty' | 'profit'
type Period = 'daily' | 'weekly' | 'monthly' | 'yearly'

function metricLabel(metric: Metric) {
  if (metric === 'qty') return 'Quantity'
  if (metric === 'profit') return 'Profit'
  return 'Total sales'
}

export default function ReportsPage() {
  const now = new Date()
  const [period, setPeriod] = useState<Period>('monthly')
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [sales, setSales] = useState<PeriodReport | null>(null)
  const [inventory, setInventory] = useState<InventoryReport | null>(null)
  const [error, setError] = useState('')
  const [metric, setMetric] = useState<Metric>('amount')

  useEffect(() => {
    setError('')
    Promise.all([
      api.salesReport(period, year, period === 'yearly' ? undefined : month),
      api.inventoryReport(),
    ])
      .then(([s, i]) => {
        setSales(s)
        setInventory(i)
      })
      .catch((e) => setError(e.message))
  }, [period, year, month])

  const topChart = useMemo(() => {
    if (!sales) return []
    return [...(sales.top_products || [])]
      .map((p) => ({
        name: p.name.length > 24 ? `${p.name.slice(0, 22)}…` : p.name,
        full: p.name,
        value: metric === 'qty' ? p.qty : metric === 'profit' ? p.profit || 0 : p.amount,
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [sales, metric])

  if (error) return <div className="error-banner">{error}</div>
  if (!sales || !inventory) return <p className="muted">Loading reports…</p>

  const trend =
    period === 'yearly'
      ? sales.by_month.map((m) => ({ label: m.month, total: m.total }))
      : sales.by_day.map((d) => ({ label: d.date.slice(5), total: d.total }))

  const years = Array.from({ length: 6 }, (_, i) => now.getFullYear() - i)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p>
            {sales.start_date} → {sales.end_date} · sales & inventory analytics
          </p>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          {(['daily', 'weekly', 'monthly', 'yearly'] as Period[]).map((p) => (
            <button key={p} className={`btn ${period === p ? '' : 'secondary'}`} onClick={() => setPeriod(p)}>
              {p}
            </button>
          ))}
          {period === 'monthly' && (
            <select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
              {MONTHS.map((label, idx) => (
                <option key={label} value={idx + 1}>
                  {label}
                </option>
              ))}
            </select>
          )}
          {(period === 'monthly' || period === 'yearly') && (
            <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      <div className="grid grid-4" style={{ marginBottom: '1rem' }}>
        <div className="stat">
          <div className="label">Total Sales</div>
          <div className="value">{peso(sales.total_sales)}</div>
        </div>
        <div className="stat">
          <div className="label">Gross Profit</div>
          <div className="value">{peso(sales.gross_profit)}</div>
        </div>
        <div className="stat">
          <div className="label">Transactions</div>
          <div className="value">{sales.transaction_count}</div>
        </div>
        <div className="stat">
          <div className="label">Items Sold</div>
          <div className="value">{sales.items_sold}</div>
        </div>
      </div>

      <div className="grid grid-2" style={{ marginBottom: '1rem' }}>
        <div className="panel">
          <h2>Sales Trend</h2>
          <div style={{ width: '100%', height: 280 }}>
            <ResponsiveContainer>
              <BarChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis dataKey="label" tick={CHART_TICK} />
                <YAxis tick={CHART_TICK} />
                <Tooltip {...CHART_TOOLTIP} formatter={(v) => peso(Number(v))} />
                <Bar dataKey="total" fill={CHART_SECONDARY} radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="panel">
          <h2>Sales by Category</h2>
          <div style={{ width: '100%', height: 280 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={sales.by_category} dataKey="total" nameKey="category" outerRadius={100}
                     stroke="var(--bg-elevated)" strokeWidth={2} label>
                  {sales.by_category.map((_, idx) => (
                    <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip {...CHART_TOOLTIP} formatter={(v) => peso(Number(v))} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>Top products — by {metricLabel(metric).toLowerCase()}</h2>
          <div className="toolbar" style={{ marginBottom: 0 }}>
            {(['amount', 'qty', 'profit'] as Metric[]).map((m) => (
              <button key={m} className={`btn ${metric === m ? '' : 'secondary'}`} onClick={() => setMetric(m)}>
                By {metricLabel(m).toLowerCase()}
              </button>
            ))}
          </div>
        </div>
        <div style={{ width: '100%', height: 320, marginTop: '0.75rem' }}>
          <ResponsiveContainer>
            <BarChart data={topChart} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
              <XAxis type="number" tick={CHART_TICK} />
              <YAxis type="category" dataKey="name" width={140} tick={CHART_TICK} />
              <Tooltip
                {...CHART_TOOLTIP}
                formatter={(v) => (metric === 'qty' ? Number(v).toLocaleString() : peso(Number(v)))}
                labelFormatter={(_, payload) => payload?.[0]?.payload?.full || ''}
              />
              <Bar
                dataKey="value"
                fill={metric === 'profit' ? CHART_OK : metric === 'qty' ? CHART_SECONDARY : CHART_ACCENT}
                radius={[0, 6, 6, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>Qty</th>
                <th>Sales</th>
                <th>Profit</th>
              </tr>
            </thead>
            <tbody>
              {sales.top_products.map((p) => (
                <tr key={p.name}>
                  <td>{p.name}</td>
                  <td>{p.qty}</td>
                  <td>{peso(p.amount)}</td>
                  <td>{peso(p.profit || 0)}</td>
                </tr>
              ))}
              {!sales.top_products.length && (
                <tr>
                  <td colSpan={4} className="muted">
                    No product sales in this period.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h2>Inventory Valuation</h2>
          <p className="muted">
            {inventory.total_skus} SKUs · {inventory.total_units} units · cost {peso(inventory.value_at_cost)} ·
            retail {peso(inventory.value_at_retail)}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th>SKUs</th>
                  <th>Units</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                {inventory.by_category.map((c) => (
                  <tr key={c.category}>
                    <td>{c.category}</td>
                    <td>{c.skus}</td>
                    <td>{c.units}</td>
                    <td>{peso(c.value_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <h2>Recent Stock Movements</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Product</th>
                  <th>Type</th>
                  <th>Change</th>
                  <th>After</th>
                  <th>Ref</th>
                </tr>
              </thead>
              <tbody>
                {inventory.movements.map((m, idx) => (
                  <tr key={idx}>
                    <td>{new Date(m.created_at).toLocaleString()}</td>
                    <td>
                      {m.product}
                      <div className="muted">{m.sku}</div>
                    </td>
                    <td>{m.type}</td>
                    <td>{m.change}</td>
                    <td>{m.after}</td>
                    <td>{m.reference || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
