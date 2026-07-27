import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, peso } from '../api'
import type { Product, Purchase, Supplier } from '../api'

export default function PurchasesPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [purchases, setPurchases] = useState<Purchase[]>([])
  const [supplierId, setSupplierId] = useState('')
  const [productId, setProductId] = useState('')
  const [qty, setQty] = useState('10')
  const [unitCost, setUnitCost] = useState('')
  const [lines, setLines] = useState<{ product: Product; quantity: number; unit_cost: number }[]>([])
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const load = () => {
    Promise.all([api.products(), api.suppliers(), api.purchases()])
      .then(([p, s, pu]) => {
        setProducts(p)
        setSuppliers(s)
        setPurchases(pu)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [])

  const addLine = () => {
    const product = products.find((p) => p.id === Number(productId))
    if (!product) return
    const quantity = Number(qty)
    const cost = unitCost ? Number(unitCost) : product.cost_price
    setLines((prev) => [...prev, { product, quantity, unit_cost: cost }])
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setOk('')
    if (!lines.length) {
      setError('Add purchase lines first')
      return
    }
    try {
      const po = await api.createPurchase({
        supplier_id: supplierId ? Number(supplierId) : null,
        items: lines.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity,
          unit_cost: l.unit_cost,
        })),
      })
      setOk(`Purchase ${po.po_no} recorded · stock increased`)
      setLines([])
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Purchase failed')
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Purchases</h1>
          <p>Receive supplier stock and update inventory quantities.</p>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {ok && <div className="success-banner">{ok}</div>}

      <div className="grid grid-2">
        <form className="panel" onSubmit={submit}>
          <h2>Receive Stock</h2>
          <div className="form-grid">
            <label className="full">
              Supplier
              <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
                <option value="">Select supplier</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Product
              <select value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">Select</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.sku} — {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Qty
              <input type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
            </label>
            <label>
              Unit Cost
              <input
                type="number"
                placeholder="Use product cost"
                value={unitCost}
                onChange={(e) => setUnitCost(e.target.value)}
              />
            </label>
          </div>
          <div style={{ margin: '0.8rem 0' }}>
            <button type="button" className="btn secondary" onClick={addLine}>
              Add line
            </button>
          </div>
          {lines.map((l, idx) => (
            <div className="cart-line" key={`${l.product.id}-${idx}`}>
              <div>
                {l.product.name}
                <div className="muted">{l.product.sku}</div>
              </div>
              <div>{l.quantity}</div>
              <div>{peso(l.quantity * l.unit_cost)}</div>
              <button type="button" className="btn secondary" onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))}>
                Remove
              </button>
            </div>
          ))}
          <button className="btn" type="submit" style={{ marginTop: '0.8rem' }}>
            Post Purchase
          </button>
        </form>

        <div className="panel">
          <h2>Purchase History</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>PO</th>
                  <th>Supplier</th>
                  <th>Date</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {purchases.map((p) => (
                  <tr key={p.id}>
                    <td>{p.po_no}</td>
                    <td>{p.supplier_name || '—'}</td>
                    <td>{new Date(p.purchase_date).toLocaleDateString()}</td>
                    <td>{peso(p.total)}</td>
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
