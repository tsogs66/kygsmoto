import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api, peso } from '../api'
import type { Customer, Product, Sale } from '../api'
import { useSortableRows } from '../hooks/useSortableRows'

type CartLine = { product: Product; quantity: number }
type Period = 'all' | 'weekly' | 'monthly' | 'yearly'

export default function SalesPage() {
  const now = new Date()
  const [products, setProducts] = useState<Product[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [sales, setSales] = useState<Sale[]>([])
  const [cart, setCart] = useState<CartLine[]>([])
  const [customerId, setCustomerId] = useState('')
  const [payment, setPayment] = useState('cash')
  const [productSearch, setProductSearch] = useState('')
  const [productId, setProductId] = useState('')
  const [qty, setQty] = useState('1')
  const [historySearch, setHistorySearch] = useState('')
  const [period, setPeriod] = useState<Period>('all')
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const load = () => {
    const params = new URLSearchParams()
    if (historySearch.trim()) params.set('q', historySearch.trim())
    if (period !== 'all') {
      params.set('period', period)
      params.set('year', String(year))
      if (period === 'monthly') params.set('month', String(month))
    }
    const qs = params.toString() ? `?${params}` : ''
    Promise.all([api.products(), api.customers(), api.sales(qs)])
      .then(([p, c, s]) => {
        setProducts(p.filter((x) => x.is_active))
        setCustomers(c)
        setSales(s)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [period, year, month])

  const filteredProducts = useMemo(() => {
    const q = productSearch.trim().toLowerCase()
    if (!q) return products
    return products.filter(
      (p) =>
        p.sku.toLowerCase().includes(q) ||
        p.name.toLowerCase().includes(q) ||
        (p.brand || '').toLowerCase().includes(q) ||
        (p.fitment || '').toLowerCase().includes(q),
    )
  }, [products, productSearch])

  const saleRows = useMemo(
    () =>
      sales.map((s) => ({
        ...s,
        customer_label: s.customer_name || 'Walk-in',
        items_label: s.items.map((i) => i.product_name).join(', '),
        item_count: s.items.length,
      })),
    [sales],
  )
  const { sorted, toggle, indicator } = useSortableRows(saleRows, 'sale_date', 'desc')

  const total = useMemo(
    () => cart.reduce((sum, line) => sum + line.quantity * line.product.sell_price, 0),
    [cart],
  )

  const addLine = () => {
    const product = products.find((p) => p.id === Number(productId))
    if (!product) return
    const quantity = Number(qty)
    if (!quantity || quantity <= 0) return
    setCart((prev) => {
      const existing = prev.find((l) => l.product.id === product.id)
      if (existing) {
        return prev.map((l) =>
          l.product.id === product.id ? { ...l, quantity: l.quantity + quantity } : l,
        )
      }
      return [...prev, { product, quantity }]
    })
    setQty('1')
  }

  const checkout = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setOk('')
    if (!cart.length) {
      setError('Add at least one item')
      return
    }
    try {
      const sale = await api.createSale({
        customer_id: customerId ? Number(customerId) : null,
        payment_method: payment,
        items: cart.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity,
          unit_price: l.product.sell_price,
        })),
      })
      setOk(`Sale ${sale.invoice_no} saved · ${peso(sale.total)}`)
      setCart([])
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sale failed')
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Sales / POS</h1>
          <p>Search items, ring up sales, and review history by week / month / year.</p>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {ok && <div className="success-banner">{ok}</div>}

      <div className="grid grid-2">
        <form className="panel" onSubmit={checkout}>
          <h2>New Sale</h2>
          <div className="form-grid">
            <label>
              Customer
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                <option value="">Walk-in</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.motorcycle_model ? ` (${c.motorcycle_model})` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Payment
              <select value={payment} onChange={(e) => setPayment(e.target.value)}>
                <option value="cash">Cash</option>
                <option value="gcash">GCash</option>
                <option value="card">Card</option>
              </select>
            </label>
            <label className="full">
              Search item
              <input
                placeholder="SKU, name, brand, fitment…"
                value={productSearch}
                onChange={(e) => {
                  setProductSearch(e.target.value)
                  setProductId('')
                }}
              />
            </label>
            <label>
              Product
              <select value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">Select item ({filteredProducts.length})</option>
                {filteredProducts.slice(0, 200).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.sku} — {p.name} (stock {p.stock_qty})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Qty
              <input type="number" min="1" step="1" value={qty} onChange={(e) => setQty(e.target.value)} />
            </label>
          </div>
          <div style={{ margin: '0.8rem 0' }}>
            <button type="button" className="btn secondary" onClick={addLine}>
              Add to cart
            </button>
          </div>

          {cart.map((line) => (
            <div className="cart-line" key={line.product.id}>
              <div>
                <strong>{line.product.name}</strong>
                <div className="muted">{line.product.sku}</div>
              </div>
              <input
                type="number"
                min="1"
                value={line.quantity}
                onChange={(e) =>
                  setCart((prev) =>
                    prev.map((l) =>
                      l.product.id === line.product.id
                        ? { ...l, quantity: Number(e.target.value) }
                        : l,
                    ),
                  )
                }
              />
              <div>{peso(line.quantity * line.product.sell_price)}</div>
              <button
                type="button"
                className="btn secondary"
                onClick={() => setCart((prev) => prev.filter((l) => l.product.id !== line.product.id))}
              >
                Remove
              </button>
            </div>
          ))}

          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '1rem', alignItems: 'center' }}>
            <strong style={{ fontFamily: 'Oswald, sans-serif', fontSize: '1.4rem' }}>Total {peso(total)}</strong>
            <button className="btn" type="submit">
              Complete Sale
            </button>
          </div>
        </form>

        <div className="panel">
          <h2>Sales History</h2>
          <div className="toolbar">
            <input
              placeholder="Search invoice / item / customer…"
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && load()}
            />
            <button className="btn secondary" type="button" onClick={load}>
              Search
            </button>
            {(['all', 'weekly', 'monthly', 'yearly'] as Period[]).map((p) => (
              <button key={p} className={`btn ${period === p ? '' : 'secondary'}`} type="button" onClick={() => setPeriod(p)}>
                {p}
              </button>
            ))}
            {period === 'monthly' && (
              <select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
                {Array.from({ length: 12 }, (_, i) => (
                  <option key={i + 1} value={i + 1}>
                    {i + 1}
                  </option>
                ))}
              </select>
            )}
            {period !== 'all' && (
              <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
                {Array.from({ length: 6 }, (_, i) => now.getFullYear() - i).map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('invoice_no')}>
                    Invoice{indicator('invoice_no')}
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('sale_date')}>
                    Date{indicator('sale_date')}
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('customer_label')}>
                    Customer{indicator('customer_label')}
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('items_label')}>
                    Items{indicator('items_label')}
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('total')}>
                    Total{indicator('total')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.slice(0, 50).map((s) => (
                  <tr key={s.id}>
                    <td>{s.invoice_no}</td>
                    <td>{new Date(s.sale_date).toLocaleDateString()}</td>
                    <td>{s.customer_label}</td>
                    <td title={s.items_label}>
                      {s.item_count} item(s)
                      <div className="muted" style={{ fontSize: '0.78rem', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {s.items_label}
                      </div>
                    </td>
                    <td>{peso(s.total)}</td>
                  </tr>
                ))}
                {!sorted.length && (
                  <tr>
                    <td colSpan={5} className="muted">
                      No sales found.
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
