import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api, peso } from '../api'
import type { Category, Product } from '../api'
import { useSortableRows } from '../hooks/useSortableRows'

export default function InventoryPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [q, setQ] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    sku: '',
    name: '',
    brand: '',
    category_id: '',
    fitment: '',
    cost_price: '0',
    sell_price: '0',
    stock_qty: '0',
    reorder_level: '5',
  })

  const load = () => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (lowOnly) params.set('low_stock', 'true')
    const qs = params.toString() ? `?${params}` : ''
    Promise.all([api.products(qs), api.categories()])
      .then(([p, c]) => {
        setProducts(p)
        setCategories(c)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [lowOnly])

  const filteredHint = useMemo(() => `${products.length} items`, [products])
  const { sorted, toggle, indicator } = useSortableRows(products, 'name', 'asc')

  const onCreate = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api.createProduct({
        sku: form.sku,
        name: form.name,
        brand: form.brand || undefined,
        category_id: form.category_id ? Number(form.category_id) : undefined,
        fitment: form.fitment || undefined,
        cost_price: Number(form.cost_price),
        sell_price: Number(form.sell_price),
        stock_qty: Number(form.stock_qty),
        reorder_level: Number(form.reorder_level),
      })
      setShowForm(false)
      setForm({
        sku: '',
        name: '',
        brand: '',
        category_id: '',
        fitment: '',
        cost_price: '0',
        sell_price: '0',
        stock_qty: '0',
        reorder_level: '5',
      })
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create product')
    }
  }

  const adjust = async (id: number) => {
    const raw = prompt('Stock change (+ add / - deduct)', '1')
    if (raw == null) return
    try {
      await api.adjustStock(id, Number(raw), 'Manual adjustment')
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Adjust failed')
    }
  }

  const remove = async (p: Product) => {
    if (!confirm(`Delete stock item ${p.sku} — ${p.name}?\nThis clears stock and deactivates the SKU.`)) return
    setError('')
    setOk('')
    try {
      const r = await api.deleteProduct(p.id, false)
      setOk(`Deleted ${p.sku} (${r.mode})`)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Inventory</h1>
          <p>Parts, oils, tires, accessories — sortable columns, adjust or delete stock.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? 'Close' : 'Add Product'}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {ok && <div className="success-banner">{ok}</div>}

      {showForm && (
        <form className="panel" onSubmit={onCreate} style={{ marginBottom: '1rem' }}>
          <h2>New Product</h2>
          <div className="form-grid">
            <label>
              SKU
              <input required value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} />
            </label>
            <label>
              Name
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label>
              Brand
              <input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} />
            </label>
            <label>
              Category
              <select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
                <option value="">Select</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="full">
              Fitment
              <input
                placeholder="Honda Click / Yamaha Mio"
                value={form.fitment}
                onChange={(e) => setForm({ ...form, fitment: e.target.value })}
              />
            </label>
            <label>
              Cost
              <input type="number" value={form.cost_price} onChange={(e) => setForm({ ...form, cost_price: e.target.value })} />
            </label>
            <label>
              Sell Price
              <input type="number" value={form.sell_price} onChange={(e) => setForm({ ...form, sell_price: e.target.value })} />
            </label>
            <label>
              Opening Stock
              <input type="number" value={form.stock_qty} onChange={(e) => setForm({ ...form, stock_qty: e.target.value })} />
            </label>
            <label>
              Reorder Level
              <input
                type="number"
                value={form.reorder_level}
                onChange={(e) => setForm({ ...form, reorder_level: e.target.value })}
              />
            </label>
          </div>
          <div style={{ marginTop: '1rem' }}>
            <button className="btn" type="submit">
              Save Product
            </button>
          </div>
        </form>
      )}

      <div className="toolbar">
        <input
          placeholder="Search SKU, name, brand, fitment…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
        />
        <button className="btn secondary" onClick={load}>
          Search
        </button>
        <button className={`btn ${lowOnly ? '' : 'secondary'}`} onClick={() => setLowOnly((v) => !v)}>
          {lowOnly ? 'Showing low stock' : 'Low stock only'}
        </button>
        <span className="muted" style={{ alignSelf: 'center' }}>
          {filteredHint}
        </span>
      </div>

      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ cursor: 'pointer' }} onClick={() => toggle('sku')}>
                  SKU{indicator('sku')}
                </th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggle('name')}>
                  Product{indicator('name')}
                </th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggle('category_name')}>
                  Category{indicator('category_name')}
                </th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggle('stock_qty')}>
                  Stock{indicator('stock_qty')}
                </th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggle('cost_price')}>
                  Cost{indicator('cost_price')}
                </th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggle('sell_price')}>
                  Price{indicator('sell_price')}
                </th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggle('stock_status')}>
                  Status{indicator('stock_status')}
                </th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr key={p.id}>
                  <td>{p.sku}</td>
                  <td>
                    <div>{p.name}</div>
                    <div className="muted" style={{ fontSize: '0.8rem' }}>
                      {p.brand}
                      {p.fitment ? ` · ${p.fitment}` : ''}
                    </div>
                  </td>
                  <td>{p.category_name || '—'}</td>
                  <td>
                    {p.stock_qty} {p.unit}
                    {!!p.reserved_qty && (
                      <div className="muted" title="Claimed by baskets held at the till">
                        {p.reserved_qty} held · {p.available_qty} free
                      </div>
                    )}
                  </td>
                  <td>{peso(p.cost_price)}</td>
                  <td>{peso(p.sell_price)}</td>
                  <td>
                    <span className={`badge ${p.stock_status}`}>{p.stock_status}</span>
                  </td>
                  <td style={{ display: 'flex', gap: '0.35rem' }}>
                    <button className="btn secondary" onClick={() => adjust(p.id)}>
                      Adjust
                    </button>
                    <button className="btn secondary" onClick={() => remove(p)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {!sorted.length && (
                <tr>
                  <td colSpan={8} className="muted">
                    No products yet. Import the KYGS workbook or add items manually.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
