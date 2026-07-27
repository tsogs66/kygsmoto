import { useEffect, useState } from 'react'
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
import type { Dashboard } from '../api'

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="error-banner">{error}</div>
  if (!data) return <p className="muted">Loading dashboard…</p>

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{data.shop_name}</h1>
          <p>Live motorshop sales, stock health, and monthly performance.</p>
        </div>
      </div>

      <div className="grid grid-4" style={{ marginBottom: '1rem' }}>
        <div className="stat">
          <div className="label">Sales Today</div>
          <div className="value">{peso(data.sales_today)}</div>
        </div>
        <div className="stat">
          <div className="label">Sales This Month</div>
          <div className="value">{peso(data.sales_month)}</div>
        </div>
        <div className="stat">
          <div className="label">Gross Profit (Month)</div>
          <div className="value">{peso(data.profit_month)}</div>
        </div>
        <div className="stat">
          <div className="label">Inventory @ Cost</div>
          <div className="value">{peso(data.inventory_value_cost)}</div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h2>6-Month Sales Trend</h2>
          <div style={{ width: '100%', height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={data.monthly_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d5d0c4" />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v) => peso(Number(v))} />
                <Bar dataKey="total" fill="#d62828" radius={[6, 6, 0, 0]} />
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
                      All stock levels healthy.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <h2>Top Products (Month)</h2>
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
                {data.top_products.map((p) => (
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
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
