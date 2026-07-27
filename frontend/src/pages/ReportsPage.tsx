import { useEffect, useState } from 'react'
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

const COLORS = ['#d62828', '#1a1f24', '#2a9d8f', '#e9c46a', '#457b9d', '#6d597a']

export default function ReportsPage() {
  const [period, setPeriod] = useState<'daily' | 'monthly' | 'yearly'>('monthly')
  const [sales, setSales] = useState<PeriodReport | null>(null)
  const [inventory, setInventory] = useState<InventoryReport | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    Promise.all([api.salesReport(period), api.inventoryReport()])
      .then(([s, i]) => {
        setSales(s)
        setInventory(i)
      })
      .catch((e) => setError(e.message))
  }, [period])

  if (error) return <div className="error-banner">{error}</div>
  if (!sales || !inventory) return <p className="muted">Loading reports…</p>

  const trend = period === 'yearly' ? sales.by_month.map((m) => ({ label: m.month, total: m.total })) : sales.by_day.map((d) => ({ label: d.date.slice(5), total: d.total }))

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p>
            {sales.start_date} → {sales.end_date} · comprehensive sales & inventory analytics
          </p>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          {(['daily', 'monthly', 'yearly'] as const).map((p) => (
            <button key={p} className={`btn ${period === p ? '' : 'secondary'}`} onClick={() => setPeriod(p)}>
              {p}
            </button>
          ))}
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
                <CartesianGrid strokeDasharray="3 3" stroke="#d5d0c4" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => peso(Number(v))} />
                <Bar dataKey="total" fill="#1a1f24" radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="panel">
          <h2>Sales by Category</h2>
          <div style={{ width: '100%', height: 280 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={sales.by_category} dataKey="total" nameKey="category" outerRadius={100} label>
                  {sales.by_category.map((_, idx) => (
                    <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => peso(Number(v))} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h2>Top Products</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Qty</th>
                  <th>Amount</th>
                </tr>
              </thead>
              <tbody>
                {sales.top_products.map((p) => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td>{p.qty}</td>
                    <td>{peso(p.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

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

        <div className="panel" style={{ gridColumn: '1 / -1' }}>
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
