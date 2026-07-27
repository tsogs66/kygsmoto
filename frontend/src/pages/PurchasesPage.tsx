import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api, peso } from '../api'
import type { OcrEditableRow, OcrPreview, Product, Purchase, Supplier } from '../api'
import { useSortableRows } from '../hooks/useSortableRows'

function localDateTimeValue(d = new Date()) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function PurchasesPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [purchases, setPurchases] = useState<Purchase[]>([])
  const [supplierId, setSupplierId] = useState('')
  const [productSearch, setProductSearch] = useState('')
  const [productId, setProductId] = useState('')
  const [qty, setQty] = useState('10')
  const [unitCost, setUnitCost] = useState('')
  const [purchaseDate, setPurchaseDate] = useState(localDateTimeValue)
  const [lines, setLines] = useState<{ product: Product; quantity: number; unit_cost: number }[]>([])
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const [photoFile, setPhotoFile] = useState<File | null>(null)
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)
  const [ocrPreview, setOcrPreview] = useState<OcrPreview | null>(null)
  const [ocrRows, setOcrRows] = useState<OcrEditableRow[]>([])
  const [ocrSupplierId, setOcrSupplierId] = useState('')
  const [ocrDate, setOcrDate] = useState(() => localDateTimeValue().slice(0, 10))
  const [busy, setBusy] = useState(false)
  const [showRaw, setShowRaw] = useState(false)

  const load = () => {
    Promise.all([api.products(), api.suppliers(), api.purchases()])
      .then(([p, s, pu]) => {
        setProducts(p.filter((x) => x.is_active !== false))
        setSuppliers(s)
        setPurchases(pu)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    return () => {
      if (photoUrl) URL.revokeObjectURL(photoUrl)
    }
  }, [photoUrl])

  const filteredProducts = useMemo(() => {
    const q = productSearch.trim().toLowerCase()
    if (!q) return products
    return products.filter(
      (p) =>
        p.sku.toLowerCase().includes(q) ||
        p.name.toLowerCase().includes(q) ||
        (p.brand || '').toLowerCase().includes(q),
    )
  }, [products, productSearch])

  const purchaseRows = useMemo(
    () =>
      purchases.map((p) => ({
        ...p,
        supplier_label: p.supplier_name || '—',
        item_count: p.items?.length || 0,
      })),
    [purchases],
  )
  const { sorted, toggle, indicator } = useSortableRows(purchaseRows, 'purchase_date', 'desc')

  const addLine = () => {
    const product = products.find((p) => p.id === Number(productId))
    if (!product) return
    const quantity = Number(qty)
    if (!quantity || quantity <= 0) return
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
        purchase_date: purchaseDate ? new Date(purchaseDate).toISOString() : null,
        items: lines.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity,
          unit_cost: l.unit_cost,
        })),
      })
      setOk(
        `Purchase ${po.po_no} recorded · stock increased · ${new Date(po.purchase_date).toLocaleString()}`,
      )
      setLines([])
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Purchase failed')
    }
  }

  const onPhoto = async (f: File | null) => {
    if (photoUrl) URL.revokeObjectURL(photoUrl)
    setPhotoFile(f)
    setPhotoUrl(f ? URL.createObjectURL(f) : null)
    setOcrPreview(null)
    setOcrRows([])
    setError('')
    if (!f) return
    setBusy(true)
    try {
      const p = await api.previewPurchasePhoto(f)
      setOcrPreview(p)
      setOcrRows(
        p.rows.map((r) => ({
          ...r,
          include: r.status !== 'blank',
          sale_date: r.sale_date ? String(r.sale_date).slice(0, 10) : ocrDate,
        })),
      )
      if (p.rows.find((r) => r.sale_date)) {
        setOcrDate(String(p.rows.find((r) => r.sale_date)?.sale_date).slice(0, 10))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Photo OCR failed')
    } finally {
      setBusy(false)
    }
  }

  const updateOcrRow = (idx: number, patch: Partial<OcrEditableRow>) => {
    setOcrRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  const selectProduct = (idx: number, productIdValue: number) => {
    const product = products.find((p) => p.id === productIdValue)
    if (!product) return
    updateOcrRow(idx, {
      matched_product_id: product.id,
      matched_product_name: product.name,
      sku: product.sku,
      product_name: product.name,
      unit_price: ocrRows[idx].unit_price || product.cost_price,
      current_stock: product.stock_qty,
      status: 'matched',
      message: `Selected ${product.sku}`,
      include: true,
    })
  }

  const runnableOcrCount = useMemo(
    () =>
      ocrRows.filter(
        (r) => r.include !== false && r.matched_product_id && Number(r.quantity) > 0,
      ).length,
    [ocrRows],
  )

  const runOcrConfirm = async () => {
    if (!ocrPreview) return
    setBusy(true)
    setError('')
    setOk('')
    try {
      const r = await api.confirmPurchaseRows({
        filename: photoFile?.name || ocrPreview.filename,
        supplier_id: ocrSupplierId ? Number(ocrSupplierId) : null,
        purchase_date: ocrDate || null,
        rows: ocrRows.map((row) => ({
          ...row,
          unit_cost: row.unit_price,
          purchase_date: row.sale_date || ocrDate,
          include: row.include !== false && !!row.matched_product_id && Number(row.quantity) > 0,
        })),
      })
      setOk(r.message)
      setOcrPreview(null)
      setOcrRows([])
      if (photoUrl) URL.revokeObjectURL(photoUrl)
      setPhotoUrl(null)
      setPhotoFile(null)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirm purchase failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Purchases</h1>
          <p>Receive supplier stock, backdate purchases, or scan a handwritten delivery report.</p>
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
            <label className="full">
              Purchase date / time
              <input
                type="datetime-local"
                value={purchaseDate}
                onChange={(e) => setPurchaseDate(e.target.value)}
              />
              <span className="muted" style={{ fontSize: '0.78rem' }}>
                Change this to enter older purchase / receiving records.
              </span>
            </label>
            <label className="full">
              Search item
              <input
                placeholder="SKU, name, brand…"
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
                <option value="">Select ({filteredProducts.length})</option>
                {filteredProducts.slice(0, 200).map((p) => (
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
              <button
                type="button"
                className="btn secondary"
                onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))}
              >
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
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('po_no')}>
                    PO{indicator('po_no')}
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('supplier_label')}>
                    Supplier{indicator('supplier_label')}
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('purchase_date')}>
                    Date{indicator('purchase_date')}
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggle('total')}>
                    Total{indicator('total')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((p) => (
                  <tr key={p.id}>
                    <td>{p.po_no}</td>
                    <td>{p.supplier_label}</td>
                    <td>{new Date(p.purchase_date).toLocaleString()}</td>
                    <td>{peso(p.total)}</td>
                  </tr>
                ))}
                {!sorted.length && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No purchases yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: '1rem' }}>
        <h2>Scan handwritten purchase / delivery report</h2>
        <p className="muted">
          Upload a photo of a supplier invoice or handwritten receiving list. Review OCR lines, select inventory
          items, set unit cost, then post as a purchase (stock increases).
        </p>
        <div className="toolbar">
          <input
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => onPhoto(e.target.files?.[0] || null)}
          />
          <select value={ocrSupplierId} onChange={(e) => setOcrSupplierId(e.target.value)}>
            <option value="">Supplier (optional)</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <input type="date" value={ocrDate} onChange={(e) => setOcrDate(e.target.value)} />
          <button className="btn" disabled={busy || runnableOcrCount === 0} onClick={runOcrConfirm}>
            {busy ? 'Working…' : `Post ${runnableOcrCount} line(s) as purchase`}
          </button>
        </div>

        {(photoUrl || ocrPreview) && (
          <div className="grid grid-2" style={{ marginTop: '1rem' }}>
            <div>
              {photoUrl && (
                <img
                  src={photoUrl}
                  alt="Purchase report scan"
                  style={{
                    width: '100%',
                    maxHeight: 420,
                    objectFit: 'contain',
                    borderRadius: 8,
                    background: '#111',
                  }}
                />
              )}
              {ocrPreview && (
                <p className="muted" style={{ marginTop: '0.6rem' }}>
                  Engine: {ocrPreview.engine} · {ocrPreview.message}
                  {ocrPreview.raw_text ? (
                    <button
                      type="button"
                      className="btn secondary"
                      style={{ marginLeft: 8 }}
                      onClick={() => setShowRaw((v) => !v)}
                    >
                      {showRaw ? 'Hide OCR text' : 'Show OCR text'}
                    </button>
                  ) : null}
                </p>
              )}
              {showRaw && ocrPreview?.raw_text && (
                <pre
                  style={{
                    whiteSpace: 'pre-wrap',
                    fontSize: '0.8rem',
                    background: '#f4f1ea',
                    padding: '0.75rem',
                    borderRadius: 8,
                    maxHeight: 200,
                    overflow: 'auto',
                  }}
                >
                  {ocrPreview.raw_text}
                </pre>
              )}
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Use</th>
                    <th>OCR / label</th>
                    <th>Select item</th>
                    <th>Qty</th>
                    <th>Unit cost</th>
                  </tr>
                </thead>
                <tbody>
                  {ocrRows.map((row, idx) => (
                    <tr key={`${row.row_number}-${idx}`}>
                      <td>
                        <input
                          type="checkbox"
                          checked={row.include !== false}
                          onChange={(e) => updateOcrRow(idx, { include: e.target.checked })}
                        />
                      </td>
                      <td style={{ minWidth: 140 }}>
                        <div className="muted" style={{ fontSize: '0.75rem' }}>
                          {row.ocr_text || '—'}
                        </div>
                        <input
                          value={row.product_name || ''}
                          placeholder="Item text"
                          onChange={(e) => updateOcrRow(idx, { product_name: e.target.value })}
                        />
                      </td>
                      <td style={{ minWidth: 200 }}>
                        <select
                          value={row.matched_product_id || ''}
                          onChange={(e) => selectProduct(idx, Number(e.target.value))}
                        >
                          <option value="">Select inventory item…</option>
                          {(row.suggestions || []).map((s) => (
                            <option key={`sug-${s.id}`} value={s.id}>
                              ★ {s.sku} — {s.name} (cost {peso(s.cost_price || 0)})
                            </option>
                          ))}
                          {products.slice(0, 400).map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.sku} — {p.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={row.quantity ?? ''}
                          onChange={(e) => updateOcrRow(idx, { quantity: Number(e.target.value) })}
                          style={{ width: 70 }}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={row.unit_price ?? ''}
                          onChange={(e) =>
                            updateOcrRow(idx, {
                              unit_price: e.target.value === '' ? null : Number(e.target.value),
                            })
                          }
                          style={{ width: 90 }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
