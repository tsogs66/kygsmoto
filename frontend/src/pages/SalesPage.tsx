import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api, peso } from '../api'
import type { Customer, Product, Sale } from '../api'

type CartLine = { product: Product; quantity: number }

export default function SalesPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [sales, setSales] = useState<Sale[]>([])
  const [cart, setCart] = useState<CartLine[]>([])
  const [customerId, setCustomerId] = useState('')
  const [payment, setPayment] = useState('cash')
  const [productId, setProductId] = useState('')
  const [qty, setQty] = useState('1')
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const load = () => {
    Promise.all([api.products(), api.customers(), api.sales()])
      .then(([p, c, s]) => {
        setProducts(p.filter((x) => x.is_active))
        setCustomers(c)
        setSales(s)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [])

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
          <p>Ring up parts and labor — stock deducts automatically.</p>
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
            <label>
              Product
              <select value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">Select item</option>
                {products.map((p) => (
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
          <h2>Recent Transactions</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Customer</th>
                  <th>Source</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {sales.slice(0, 20).map((s) => (
                  <tr key={s.id}>
                    <td>{s.invoice_no}</td>
                    <td>{s.customer_name || 'Walk-in'}</td>
                    <td>{s.source}</td>
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
