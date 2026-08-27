import { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, peso } from '../api'
import type { AbcOut, MoversOut, OverviewOut, ProductForecast, ReorderOut } from '../api'
import { CHART_ACCENT, CHART_GRID, CHART_TICK, CHART_TOOLTIP } from '../chartTheme'

type Tab = 'reorder' | 'fast' | 'dead' | 'abc'

const TABS: { key: Tab; label: string }[] = [
  { key: 'reorder', label: 'What to order' },
  { key: 'fast', label: 'Fast movers' },
  { key: 'dead', label: 'Dead stock' },
  { key: 'abc', label: 'ABC / XYZ' },
]

function movementClass(movement: string) {
  return `pill pill-${movement}`
}

export default function StockIntelligencePage() {
  const [tab, setTab] = useState<Tab>('reorder')
  const [days, setDays] = useState(90)
  const [overview, setOverview] = useState<OverviewOut | null>(null)
  const [reorder, setReorder] = useState<ReorderOut | null>(null)
  const [movers, setMovers] = useState<MoversOut | null>(null)
  const [abc, setAbc] = useState<AbcOut | null>(null)
  const [detail, setDetail] = useState<ProductForecast | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    api.stockOverview(days).then(setOverview).catch((e) => setError(e.message))
  }, [days])

  useEffect(() => {
    setError('')
    setLoading(true)
    const load = async () => {
      try {
        if (tab === 'reorder') setReorder(await api.reorder(days))
        else if (tab === 'abc') setAbc(await api.abc(days))
        else setMovers(await api.movers(tab, days))
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not load')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [tab, days])

  const openForecast = async (productId: number) => {
    try {
      setDetail(await api.productForecast(productId))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load forecast')
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Stock Intelligence</h1>
          <p className="muted">
            Demand forecasts, movement classes and what to order next.
          </p>
        </div>
        <div className="toolbar">
          <label className="label">
            Look back
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
              <option value={90}>90 days</option>
              <option value={180}>180 days</option>
              <option value={365}>1 year</option>
            </select>
          </label>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {overview && (
        <div className="grid grid-4">
          <div className="panel stat">
            <div className="label">Lines to order</div>
            <div className="value">{overview.reorder_lines}</div>
            <div className="muted">{peso(overview.reorder_cost)} at cost</div>
          </div>
          <div className="panel stat">
            <div className="label">Out of stock</div>
            <div className="value">{overview.out_of_stock}</div>
            <div className="muted">{overview.fast_movers_out_of_stock} are fast movers</div>
          </div>
          <div className="panel stat">
            <div className="label">Dead stock value</div>
            <div className="value">{peso(overview.dead_stock_value)}</div>
            <div className="muted">{overview.dead_stock_pct}% of stock value</div>
          </div>
          <div className="panel stat">
            <div className="label">Stock turnover</div>
            <div className="value">{overview.stock_turnover_annualised}&times;</div>
            <div className="muted">annualised</div>
          </div>
        </div>
      )}

      <div className="toolbar" style={{ margin: '1rem 0' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`btn ${tab === t.key ? '' : 'secondary'}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && <div className="panel muted">Crunching the numbers&hellip;</div>}

      {!loading && tab === 'reorder' && reorder && (
        <div className="panel">
          <h2>Suggested purchases</h2>
          <p className="muted">
            {reorder.count} line(s), {peso(reorder.total_cost)} across{' '}
            {reorder.by_supplier.length} supplier(s). Ranked by urgency.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Urgency</th><th>Item</th><th>Class</th>
                  <th className="num">On hand</th><th className="num">Per month</th>
                  <th className="num">Reorder at</th><th className="num">Order</th>
                  <th className="num">Cost</th><th>Why</th>
                </tr>
              </thead>
              <tbody>
                {reorder.suggestions.map((r) => (
                  <tr key={r.product_id} onClick={() => openForecast(r.product_id)}
                      style={{ cursor: 'pointer' }}>
                    <td>{r.urgency.toFixed(0)}</td>
                    <td>
                      <strong>{r.name}</strong>
                      <div className="muted">{r.sku} · {r.supplier || 'no supplier'}</div>
                    </td>
                    <td><span className={movementClass(r.movement)}>{r.abc} {r.movement}</span></td>
                    <td className="num">{r.on_hand}</td>
                    <td className="num">{r.monthly_rate.toFixed(1)}</td>
                    <td className="num">{r.reorder_point.toFixed(0)}</td>
                    <td className="num"><strong>{r.suggested_qty}</strong></td>
                    <td className="num">{peso(r.order_cost)}</td>
                    <td className="muted">{r.reason}</td>
                  </tr>
                ))}
                {!reorder.suggestions.length && (
                  <tr><td colSpan={9} className="muted">Nothing needs reordering.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && (tab === 'fast' || tab === 'dead') && movers && (
        <div className="panel">
          <h2>{tab === 'fast' ? 'Fastest moving items' : 'Dead stock — cash on the shelf'}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Item</th><th>Movement</th><th>Pattern</th>
                  <th className="num">Sold</th><th className="num">Per month</th>
                  <th className="num">On hand</th><th className="num">Stock value</th>
                  <th className="num">Cover</th><th>Last sold</th>
                </tr>
              </thead>
              <tbody>
                {movers.items.map((r) => (
                  <tr key={r.product_id} onClick={() => openForecast(r.product_id)}
                      style={{ cursor: 'pointer' }}>
                    <td>
                      <strong>{r.name}</strong>
                      <div className="muted">{r.sku}</div>
                    </td>
                    <td><span className={movementClass(r.movement)}>{r.movement}</span></td>
                    <td className="muted">{r.demand_pattern}</td>
                    <td className="num">{r.sold_qty}</td>
                    <td className="num">{r.monthly_rate.toFixed(1)}</td>
                    <td className="num">{r.on_hand}</td>
                    <td className="num">{peso(r.stock_value)}</td>
                    <td className="num">{r.days_of_cover === null ? '∞' : `${r.days_of_cover}d`}</td>
                    <td className="muted">{r.last_sold || 'never'}</td>
                  </tr>
                ))}
                {!movers.items.length && (
                  <tr><td colSpan={9} className="muted">Nothing to show.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && tab === 'abc' && abc && (
        <>
          <div className="grid grid-2">
            <div className="panel">
              <h2>Value classes</h2>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Class</th><th className="num">Items</th><th className="num">Revenue</th><th className="num">Stock value</th></tr></thead>
                  <tbody>
                    {abc.summary.map((s) => (
                      <tr key={s.class}>
                        <td><strong>{s.class}</strong></td>
                        <td className="num">{s.items}</td>
                        <td className="num">{peso(s.revenue)}</td>
                        <td className="num">{peso(s.stock_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="panel">
              <h2>Stocking policy</h2>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Cell</th><th className="num">Items</th><th>Recommended policy</th></tr></thead>
                  <tbody>
                    {abc.matrix.map((m) => (
                      <tr key={m.cell}>
                        <td><strong>{m.cell}</strong></td>
                        <td className="num">{m.items}</td>
                        <td className="muted">{m.policy}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}

      {detail && (
        <div className="backdrop" onClick={() => setDetail(null)}>
          <div className="panel modal" onClick={(e) => e.stopPropagation()}
               style={{ maxWidth: 820, margin: '4vh auto', maxHeight: '88vh', overflowY: 'auto' }}>
            <div className="page-header">
              <div>
                <h2>{detail.product.name}</h2>
                <p className="muted">{detail.product.sku} · {detail.product.supplier || 'no supplier'}</p>
              </div>
              <button className="btn secondary" onClick={() => setDetail(null)}>Close</button>
            </div>

            <div className="grid grid-4">
              <div className="stat"><div className="label">Pattern</div>
                <div className="value" style={{ fontSize: '1.1rem' }}>{detail.pattern.pattern}</div>
                <div className="muted">via {detail.pattern.method || '—'}</div></div>
              <div className="stat"><div className="label">Next 30 days</div>
                <div className="value">{detail.forecast.next_30d}</div>
                <div className="muted">units forecast</div></div>
              <div className="stat"><div className="label">Reorder point</div>
                <div className="value">{detail.replenishment.reorder_point}</div>
                <div className="muted">incl. {detail.replenishment.safety_stock} safety</div></div>
              <div className="stat"><div className="label">Order qty</div>
                <div className="value">{detail.replenishment.economic_order_qty}</div>
                <div className="muted">economic order quantity</div></div>
            </div>

            <h3>Weekly demand</h3>
            <div style={{ width: '100%', height: 220 }}>
              <ResponsiveContainer>
                <BarChart data={detail.weekly_demand}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                  <XAxis dataKey="week_of" tick={CHART_TICK} />
                  <YAxis tick={CHART_TICK} />
                  <Tooltip {...CHART_TOOLTIP} />
                  <Bar dataKey="qty" fill={CHART_ACCENT} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <h3>Replenishment plan</h3>
            <div className="table-wrap">
              <table>
                <tbody>
                  <tr><td>On hand now</td><td className="num">{detail.product.stock_qty}</td></tr>
                  <tr><td>Days of cover</td>
                    <td className="num">{detail.replenishment.days_of_cover ?? '∞'}</td></tr>
                  <tr><td>Projected stockout</td>
                    <td className="num">{detail.replenishment.projected_stockout || '—'}</td></tr>
                  <tr><td>Supplier lead time</td>
                    <td className="num">{detail.replenishment.lead_time_days} days</td></tr>
                  <tr><td>Review cycle</td>
                    <td className="num">{detail.replenishment.review_days} days</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
