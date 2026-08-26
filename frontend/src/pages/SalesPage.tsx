import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api, peso } from '../api'
import type { Customer, HeldSale, Product, Sale } from '../api'
import { useSortableRows } from '../hooks/useSortableRows'
import CustomerSelect from '../components/CustomerSelect'

type CartLine = { product: Product; quantity: number; discount: number }
type Period = 'all' | 'weekly' | 'monthly' | 'yearly'

export default function SalesPage() {
  const now = new Date()
  const [products, setProducts] = useState<Product[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [sales, setSales] = useState<Sale[]>([])
  const [cart, setCart] = useState<CartLine[]>([])
  const [customerId, setCustomerId] = useState<number | null>(null)
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
  const [holds, setHolds] = useState<HeldSale[]>([])
  const [showHold, setShowHold] = useState(false)
  const [holdInfo, setHoldInfo] = useState({
    label: '', customer_name: '', contact: '', plate_no: '', motorcycle: '', note: '',
  })
  const [holdSaveCustomer, setHoldSaveCustomer] = useState(false)
  const [saleDate, setSaleDate] = useState(() => {
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
  })

  const load = () => {
    const params = new URLSearchParams()
    if (historySearch.trim()) params.set('q', historySearch.trim())
    if (period !== 'all') {
      params.set('period', period)
      params.set('year', String(year))
      if (period === 'monthly') params.set('month', String(month))
    }
    const qs = params.toString() ? `?${params}` : ''
    api.holds().then((h) => setHolds(h.holds)).catch(() => undefined)
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

  /** A line never goes below zero, however large the discount typed. */
  const lineTotal = (line: CartLine) =>
    Math.max(0, line.quantity * line.product.sell_price - (line.discount || 0))

  const total = useMemo(
    () => cart.reduce((sum, line) => sum + lineTotal(line), 0),
    [cart],
  )
  const discountTotal = useMemo(
    () => cart.reduce((sum, line) => sum + Math.min(
      line.discount || 0, line.quantity * line.product.sell_price), 0),
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
      return [...prev, { product, quantity, discount: 0 }]
    })
    setQty('1')
  }

  const selectedCustomer = customers.find((c) => c.id === customerId) || null

  const holdSale = async () => {
    if (!cart.length) {
      setError('Add at least one item before holding')
      return
    }
    setError('')
    try {
      const held = await api.createHold({
        ...holdInfo,
        customer_id: customerId,
        customer_name: holdInfo.customer_name || selectedCustomer?.name || '',
        payment_method: payment,
        save_customer: customerId ? false : holdSaveCustomer,
        lines: cart.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity,
          unit_price: l.product.sell_price,
          discount: l.discount || 0,
        })),
      })
      setOk(`Held as ${held.reference}${held.customer_name ? ` for ${held.customer_name}` : ''}`)
      setCart([])
      setCustomerId(null)
      setShowHold(false)
      setHoldSaveCustomer(false)
      setHoldInfo({ label: '', customer_name: '', contact: '', plate_no: '',
                    motorcycle: '', note: '' })
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not hold the sale')
    }
  }

  /** Put a held basket back on the till, and clear the hold. */
  const resumeHold = async (held: HeldSale) => {
    const lines = held.lines
      .map((l) => {
        const product = products.find((p) => p.id === l.product_id)
        return product
          ? { product, quantity: l.quantity, discount: l.discount || 0 }
          : null
      })
      .filter((l): l is CartLine => l !== null)

    if (lines.length !== held.lines.length) {
      setError('Some held items are no longer in inventory — check the basket')
    }
    setCart(lines)
    setCustomerId(held.customer_id)
    setPayment(held.payment_method || 'cash')
    await api.deleteHold(held.id)
    setOk(`Resumed ${held.reference}`)
    load()
  }

  const discardHold = async (held: HeldSale) => {
    if (!window.confirm(`Discard ${held.reference}? The basket is lost.`)) return
    await api.deleteHold(held.id)
    setOk(`Discarded ${held.reference}`)
    load()
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
        customer_id: customerId,
        payment_method: payment,
        sale_date: saleDate ? new Date(saleDate).toISOString() : null,
        items: cart.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity,
          unit_price: l.product.sell_price,
          discount: l.discount || 0,
        })),
      })
      setOk(`Sale ${sale.invoice_no} saved · ${peso(sale.total)} · ${new Date(sale.sale_date).toLocaleString()}`)
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
          <p>Search items, ring up or backdate sales, and review history by week / month / year.</p>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {ok && <div className="success-banner">{ok}</div>}

      {holds.length > 0 && (
        <div className="panel" style={{ marginBottom: '1rem' }}>
          <div className="page-header">
            <div>
              <h2>Held sales ({holds.length})</h2>
              <p className="muted">Parked baskets — oldest first. No stock is reserved.</p>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th><th>Customer</th><th>Why</th>
                  <th className="num">Lines</th><th className="num">Value</th>
                  <th className="num">Waiting</th><th />
                </tr>
              </thead>
              <tbody>
                {holds.map((h) => (
                  <tr key={h.id}>
                    <td><strong>{h.reference}</strong></td>
                    <td>
                      {h.customer_name || 'Walk-in'}
                      <div className="muted">
                        {[h.plate_no, h.motorcycle, h.contact].filter(Boolean).join(' · ')}
                      </div>
                    </td>
                    <td className="muted">{h.label || '—'}</td>
                    <td className="num">{h.line_count}</td>
                    <td className="num">{peso(h.total)}</td>
                    <td className="num">{h.held_for_minutes ?? 0}m</td>
                    <td className="nowrap">
                      <button className="btn" type="button"
                              onClick={() => resumeHold(h)}>Resume</button>
                      <button className="btn secondary" type="button"
                              onClick={() => discardHold(h)}>Discard</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid grid-2">
        <form className="panel" onSubmit={checkout}>
          <h2>New Sale</h2>
          <div className="form-grid">
            <label>
              Customer
              <CustomerSelect
                customers={customers}
                value={customerId}
                onSelect={(c) => setCustomerId(c ? c.id : null)}
                onCreated={(c) => setCustomers((prev) => [...prev, c])}
              />
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
              Sale date / time
              <input
                type="datetime-local"
                value={saleDate}
                onChange={(e) => setSaleDate(e.target.value)}
              />
              <span className="muted" style={{ fontSize: '0.78rem' }}>
                Change this to enter older sales into the existing system.
              </span>
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
              <label className="muted" style={{ fontSize: '0.72rem' }}>
                Less
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={line.discount}
                  style={{ width: 80 }}
                  onChange={(e) =>
                    setCart((prev) =>
                      prev.map((l) =>
                        l.product.id === line.product.id
                          ? { ...l, discount: Math.max(0, Number(e.target.value) || 0) }
                          : l,
                      ),
                    )
                  }
                />
              </label>
              <div>{peso(lineTotal(line))}</div>
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
            <strong style={{ fontFamily: 'Oswald, sans-serif', fontSize: '1.4rem' }}>
              Total {peso(total)}
              {discountTotal > 0 && (
                <span className="muted" style={{ fontSize: '0.8rem', fontWeight: 400 }}>
                  {' '}· less {peso(discountTotal)}
                </span>
              )}
            </strong>
            <span className="toolbar">
              <button className="btn secondary" type="button"
                      onClick={() => setShowHold((v) => !v)}>
                {showHold ? 'Cancel hold' : 'Hold sale'}
              </button>
              <button className="btn" type="submit">
                Complete Sale
              </button>
            </span>
          </div>
          {showHold && (
            <div className="panel" style={{ marginTop: '1rem' }}>
              <h3>Hold this sale</h3>
              <p className="muted">
                Who is it for? Enough detail to find it again when they come back.
              </p>
              <div className="grid grid-2">
                <label className="label">Customer
                  <CustomerSelect
                    customers={customers}
                    value={customerId}
                    walkInName={holdInfo.customer_name}
                    onSelect={(c) => {
                      setCustomerId(c ? c.id : null)
                      if (c) {
                        setHoldInfo((h) => ({
                          ...h,
                          customer_name: c.name,
                          contact: c.phone || h.contact,
                          motorcycle: c.motorcycle_model || h.motorcycle,
                        }))
                        setHoldSaveCustomer(false)
                      }
                    }}
                    onWalkInName={(name) =>
                      setHoldInfo((h) => ({ ...h, customer_name: name }))}
                    onCreated={(c) => setCustomers((prev) => [...prev, c])}
                  />
                </label>
                <label className="label">Contact number
                  <input value={holdInfo.contact}
                         onChange={(e) => setHoldInfo({ ...holdInfo, contact: e.target.value })} />
                </label>
                <label className="label">Plate number
                  <input value={holdInfo.plate_no}
                         onChange={(e) => setHoldInfo({ ...holdInfo, plate_no: e.target.value })} />
                </label>
                <label className="label">Motorcycle
                  <input value={holdInfo.motorcycle}
                         onChange={(e) =>
                           setHoldInfo({ ...holdInfo, motorcycle: e.target.value })} />
                </label>
              </div>
              <label className="label">Why is it on hold?
                <input placeholder="e.g. gone to the ATM, waiting for a part"
                       value={holdInfo.label}
                       onChange={(e) => setHoldInfo({ ...holdInfo, label: e.target.value })} />
              </label>
              {!customerId && holdInfo.customer_name.trim() && (
                <label className="label" style={{ display: 'flex', gap: '0.5rem',
                                                  alignItems: 'center' }}>
                  <input type="checkbox" checked={holdSaveCustomer} style={{ width: 'auto' }}
                         onChange={(e) => setHoldSaveCustomer(e.target.checked)} />
                  <span>Save “{holdInfo.customer_name.trim()}” as a customer</span>
                </label>
              )}
              <button className="btn" type="button" onClick={holdSale}>
                Hold {peso(total)}
              </button>
            </div>
          )}
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
