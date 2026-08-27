import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, peso } from '../api'
import type { Dashboard, ProductStat } from '../api'
import {
  CHART_ACCENT, CHART_GRID, CHART_SECONDARY, CHART_TICK, CHART_TICK_LG,
  CHART_TOOLTIP,
} from '../chartTheme'

type Metric = 'amount' | 'qty' | 'profit'
type PerfPeriod = 'monthly' | 'yearly'

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function chartValue(item: ProductStat, metric: Metric) {
  if (metric === 'qty') return item.qty
  if (metric === 'profit') return item.profit || 0
  return item.amount
}

function metricLabel(metric: Metric) {
  if (metric === 'qty') return 'Quantity'
  if (metric === 'profit') return 'Profit'
  return 'Total sales'
}

export default function DashboardPage() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')
  const [metric, setMetric] = useState<Metric>('amount')
  const [perfPeriod, setPerfPeriod] = useState<PerfPeriod>('monthly')

  useEffect(() => {
    setError('')
    api
      .dashboard(year, month)
      .then(setData)
      .catch((e) => setError(e.message))
  }, [year, month])

  const movers = useMemo(() => {
    if (!data) return []
    const source = perfPeriod === 'yearly' ? data.top_products_year : data.top_products_month
    return [...source]
      .sort((a, b) => chartValue(b, metric) - chartValue(a, metric))
      .slice(0, 10)
      .map((p) => ({
        name: p.name.length > 28 ? `${p.name.slice(0, 26)}…` : p.name,
        full: p.name,
        value: chartValue(p, metric),
      }))
  }, [data, metric, perfPeriod])

  const profitable = useMemo(() => {
    if (!data) return []
    const source = perfPeriod === 'yearly' ? data.top_profit_year : data.top_profit_month
    return [...source]
      .sort((a, b) => chartValue(b, metric === 'qty' ? 'qty' : metric === 'amount' ? 'amount' : 'profit') - chartValue(a, metric === 'qty' ? 'qty' : metric === 'amount' ? 'amount' : 'profit'))
      .slice(0, 10)
      .map((p) => ({
        name: p.name.length > 28 ? `${p.name.slice(0, 26)}…` : p.name,
        full: p.name,
        value: chartValue(p, metric),
      }))
  }, [data, metric, perfPeriod])

  if (error) return <div className="error-banner">{error}</div>
  if (!data) return <p className="muted">Loading dashboard…</p>

  const years = Array.from({ length: 6 }, (_, i) => now.getFullYear() - i)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{data.shop_name}</h1>
          <p>Live motorshop sales, stock health, and product performance.</p>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
            {MONTHS.map((label, idx) => (
              <option key={label} value={idx + 1}>
                {label}
              </option>
            ))}
          </select>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-4" style={{ marginBottom: '1rem' }}>
        <div className="stat">
          <div className="label">Sales Today</div>
          <div className="value">{peso(data.sales_today)}</div>
        </div>
        <div className="stat">
          <div className="label">Sales This Week</div>
          <div className="value">{peso(data.sales_week)}</div>
        </div>
        <div className="stat">
          <div className="label">Sales ({MONTHS[month - 1]})</div>
          <div className="value">{peso(data.sales_month)}</div>
        </div>
        <div className="stat">
          <div className="label">Gross Profit (Month)</div>
          <div className="value">{peso(data.profit_month)}</div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>Product performance</h2>
          <div className="toolbar" style={{ marginBottom: 0 }}>
            {(['monthly', 'yearly'] as PerfPeriod[]).map((p) => (
              <button key={p} className={`btn ${perfPeriod === p ? '' : 'secondary'}`} onClick={() => setPerfPeriod(p)}>
                {p}
              </button>
            ))}
            {(['amount', 'qty', 'profit'] as Metric[]).map((m) => (
              <button key={m} className={`btn ${metric === m ? '' : 'secondary'}`} onClick={() => setMetric(m)}>
                By {metricLabel(m).toLowerCase()}
              </button>
            ))}
          </div>
        </div>
        <p className="muted">
          Viewing {perfPeriod} graphs ranked by {metricLabel(metric).toLowerCase()} for {MONTHS[month - 1]} {year}
          {perfPeriod === 'yearly' ? ` / full year ${year}` : ''}.
        </p>
        <div className="grid grid-2">
          <div>
            <h2>Top moving products</h2>
            <div style={{ width: '100%', height: 300 }}>
              <ResponsiveContainer>
                <BarChart data={movers} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                  <XAxis type="number" tick={CHART_TICK} />
                  <YAxis type="category" dataKey="name" width={140} tick={CHART_TICK} />
                  <Tooltip
                    {...CHART_TOOLTIP}
                    formatter={(v) =>
                      metric === 'qty' ? Number(v).toLocaleString() : peso(Number(v))
                    }
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.full || ''}
                  />
                  <Bar dataKey="value" fill={CHART_ACCENT} radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div>
            <h2>Top profitable / ranked items</h2>
            <div style={{ width: '100%', height: 300 }}>
              <ResponsiveContainer>
                <BarChart data={profitable} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                  <XAxis type="number" tick={CHART_TICK} />
                  <YAxis type="category" dataKey="name" width={140} tick={CHART_TICK} />
                  <Tooltip
                    {...CHART_TOOLTIP}
                    formatter={(v) =>
                      metric === 'qty' ? Number(v).toLocaleString() : peso(Number(v))
                    }
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.full || ''}
                  />
                  <Bar dataKey="value" fill={CHART_SECONDARY} radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h2>6-Month Sales Trend</h2>
          <div style={{ width: '100%', height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={data.monthly_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis dataKey="label" tick={CHART_TICK_LG} />
                <YAxis tick={CHART_TICK_LG} />
                <Tooltip {...CHART_TOOLTIP} formatter={(v) => peso(Number(v))} />
                <Bar dataKey="total" fill={CHART_ACCENT} radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="panel">
          <h2>Stock Alerts</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            {data.low_stock_count} low · {data.out_of_stock_count} out of stock · {data.total_products} active SKUs
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.low_stock_items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.sku}</td>
                    <td>{item.name}</td>
                    <td>
                      {item.stock_qty} / {item.reorder_level}
                    </td>
                    <td>
                      <span className={`badge ${item.status}`}>{item.status}</span>
                    </td>
                  </tr>
                ))}
                {!data.low_stock_items.length && (
                  <tr>
                    <td colSpan={4} className="muted">
                      {data.total_products === 0
                        ? 'No inventory yet — import KYGS workbook or add products.'
                        : 'All stock levels healthy.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <h2>
            Top Products — {MONTHS[month - 1]} {year}
          </h2>
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
                {(data.top_products_month.length ? data.top_products_month : data.top_products).map((p) => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td>{p.qty}</td>
                    <td>{peso(p.amount)}</td>
                    <td>{peso(p.profit || 0)}</td>
                  </tr>
                ))}
                {!data.top_products_month.length && !data.top_products.length && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No sales in this month.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <h2>Recent Sales</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Customer</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_sales.map((s) => (
                  <tr key={s.id}>
                    <td>{s.invoice_no}</td>
                    <td>{s.customer}</td>
                    <td>{peso(s.total)}</td>
                  </tr>
                ))}
                {!data.recent_sales.length && (
                  <tr>
                    <td colSpan={3} className="muted">
                      No sales yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
