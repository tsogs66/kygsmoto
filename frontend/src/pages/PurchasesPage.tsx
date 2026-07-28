import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api, peso } from '../api'
import type { OcrEditableRow, OcrPreview, Product, Purchase, Supplier } from '../api'
import { useSortableRows } from '../hooks/useSortableRows'
import ProductSearchSelect from '../components/ProductSearchSelect'

function pad2(n: number) {
  return String(n).padStart(2, '0')
}

/** Current local wall time for datetime-local inputs. */
function localDateTimeValue(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/**
 * Map API naive datetime → datetime-local value without UTC shift.
 * Server stores wall-clock times (no timezone); Date#toISOString would skew them.
 */
function apiDateTimeToInput(value?: string | null) {
  if (!value) return localDateTimeValue()
  const m = String(value).match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
  if (m) return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}`
  return localDateTimeValue(new Date(value))
}

/** datetime-local → API naive datetime (keep the digits the user picked). */
function inputDateTimeToApi(value: string) {
  if (!value) return null
  return value.length === 16 ? `${value}:00` : value
}

function formatApiDateTime(value?: string | null) {
  if (!value) return '—'
  const m = String(value).match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]))
    return d.toLocaleString()
  }
  return new Date(value).toLocaleString()
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

  const [editing, setEditing] = useState<Purchase | null>(null)
  const [editSupplierId, setEditSupplierId] = useState('')
  const [editDate, setEditDate] = useState('')
  const [editNotes, setEditNotes] = useState('')
  const [editLines, setEditLines] = useState<
    { id?: number; product_id: number; product?: Product; quantity: number; unit_cost: number }[]
  >([])
  const [editProductId, setEditProductId] = useState('')
  const [editQty, setEditQty] = useState('1')
  const [editCost, setEditCost] = useState('')
  const [receiptBusy, setReceiptBusy] = useState(false)

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

  const applyEditingPurchase = (p: Purchase) => {
    setEditing(p)
    setEditSupplierId(p.supplier_id ? String(p.supplier_id) : '')
    setEditDate(apiDateTimeToInput(p.purchase_date))
    setEditNotes(p.notes || '')
    setEditLines(
      (p.items || []).map((i) => ({
        id: i.id,
        product_id: i.product_id,
        product: products.find((x) => x.id === i.product_id),
        quantity: i.quantity,
        unit_cost: i.unit_cost,
      })),
    )
  }

  const openEdit = async (p: Purchase) => {
    setError('')
    setOk('')
    applyEditingPurchase(p)
    try {
      const fresh = await api.getPurchase(p.id)
      applyEditingPurchase(fresh)
    } catch (err) {
      // Keep list snapshot if detail fetch fails
      setError(err instanceof Error ? err.message : 'Could not load purchase')
    }
  }

  const addEditLine = () => {
    const product = products.find((p) => p.id === Number(editProductId))
    if (!product) return false
    const quantity = Number(editQty)
    if (!quantity || quantity <= 0) return false
    const cost = editCost ? Number(editCost) : product.cost_price
    setEditLines((prev) => [...prev, { product_id: product.id, product, quantity, unit_cost: cost }])
    setEditProductId('')
    setEditQty('1')
    setEditCost('')
    return true
  }

  const saveEdit = async () => {
    if (!editing) return

    // Include product selected in the picker even if "Add item" wasn't clicked.
    let lines = editLines
    if (editProductId) {
      const product = products.find((p) => p.id === Number(editProductId))
      const quantity = Number(editQty)
      if (product && quantity > 0) {
        const cost = editCost ? Number(editCost) : product.cost_price
        lines = [...lines, { product_id: product.id, product, quantity, unit_cost: cost }]
        setEditLines(lines)
        setEditProductId('')
        setEditQty('1')
        setEditCost('')
      }
    }

    if (!lines.length) {
      setError('Purchase needs at least one item')
      return
    }
    for (const l of lines) {
      if (!l.quantity || l.quantity <= 0 || Number.isNaN(l.quantity)) {
        setError('Each line needs a quantity greater than 0')
        return
      }
    }

    setBusy(true)
    setError('')
    setOk('')
    try {
      const updated = await api.updatePurchase(editing.id, {
        supplier_id: editSupplierId ? Number(editSupplierId) : null,
        purchase_date: inputDateTimeToApi(editDate),
        notes: editNotes,
        items: lines.map((l) => ({
          id: l.id,
          product_id: l.product_id,
          quantity: Number(l.quantity),
          unit_cost: Number(l.unit_cost),
        })),
      })
      setOk(`Updated ${updated.po_no}`)
      applyEditingPurchase(updated)
      setPurchases((prev) => {
        const next = prev.map((p) => (p.id === updated.id ? updated : p))
        if (!next.find((p) => p.id === updated.id)) next.unshift(updated)
        return next
      })
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  const onReceiptUpload = async (purchaseId: number, file: File | null) => {
    if (!file) return
    setReceiptBusy(true)
    setError('')
    try {
      const r = await api.uploadPurchaseReceipt(purchaseId, file)
      setOk(r.message)
      if (editing?.id === purchaseId) {
        const fresh = await api.getPurchase(purchaseId)
        setEditing(fresh)
      }
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Receipt upload failed')
    } finally {
      setReceiptBusy(false)
    }
  }

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
        purchase_date: inputDateTimeToApi(purchaseDate),
        items: lines.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity,
          unit_cost: l.unit_cost,
        })),
      })
      setOk(
        `Purchase ${po.po_no} recorded · stock increased · ${formatApiDateTime(po.purchase_date)}`,
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
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), 50000)
    try {
      const p = await api.previewPurchasePhoto(f, ctrl.signal)
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
      const msg =
        err instanceof Error && err.name === 'AbortError'
          ? 'OCR timed out. Try a smaller JPG or enter lines manually.'
          : err instanceof Error
            ? err.message
            : 'Photo OCR failed'
      setError(msg)
      setOcrRows(
        Array.from({ length: 5 }, (_, i) => ({
          row_number: i + 1,
          quantity: 1,
          include: true,
          status: 'blank',
          sale_date: ocrDate,
          message: 'Enter manually',
        })),
      )
    } finally {
      window.clearTimeout(timer)
      setBusy(false)
    }
  }

  const updateOcrRow = (idx: number, patch: Partial<OcrEditableRow>) => {
    setOcrRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  const selectProduct = (idx: number, productIdValue: number) => {
    const product = products.find((p) => p.id === productIdValue)
    if (!product) return
    const row = ocrRows[idx]
    updateOcrRow(idx, {
      matched_product_id: product.id,
      matched_product_name: product.name,
      // Keep invoice Item Code / description when present
      sku: row.sku || product.sku,
      product_name: row.product_name || product.name,
      unit_price: row.unit_price || product.cost_price,
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
                  <th>Receipt</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((p) => (
                  <tr key={p.id}>
                    <td>{p.po_no}</td>
                    <td>{p.supplier_label}</td>
                    <td>{formatApiDateTime(p.purchase_date)}</td>
                    <td>{peso(p.total)}</td>
                    <td>
                      {p.has_receipt ? (
                        <a href={api.purchaseReceiptUrl(p.id)} target="_blank" rel="noreferrer">
                          {p.receipt_filename || 'View'}
                        </a>
                      ) : (
                        <span className="muted">None</span>
                      )}
                      <div style={{ marginTop: 4 }}>
                        <label className="btn secondary" style={{ display: 'inline-block', fontSize: '0.75rem', padding: '0.2rem 0.45rem' }}>
                          {receiptBusy ? '…' : 'Upload'}
                          <input
                            type="file"
                            accept="image/*,.pdf,application/pdf"
                            hidden
                            onChange={(e) => onReceiptUpload(p.id, e.target.files?.[0] || null)}
                          />
                        </label>
                      </div>
                    </td>
                    <td>
                      <button type="button" className="btn secondary" onClick={() => openEdit(p)}>
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
                {!sorted.length && (
                  <tr>
                    <td colSpan={6} className="muted">
                      No purchases yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {editing && (
        <div className="panel" style={{ marginTop: '1rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0 }}>Edit {editing.po_no}</h2>
            <button type="button" className="btn secondary" onClick={() => setEditing(null)}>
              Close
            </button>
          </div>
          <p className="muted">Change items, qty, cost, or date. Stock adjusts by the quantity difference.</p>
          <div className="form-grid">
            <label>
              Supplier
              <select value={editSupplierId} onChange={(e) => setEditSupplierId(e.target.value)}>
                <option value="">None</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Purchase date / time
              <input type="datetime-local" value={editDate} onChange={(e) => setEditDate(e.target.value)} />
            </label>
            <label className="full">
              Notes
              <input value={editNotes} onChange={(e) => setEditNotes(e.target.value)} />
            </label>
          </div>

          <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Unit cost</th>
                  <th>Line</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {editLines.map((l, idx) => (
                  <tr key={`${l.id || 'n'}-${l.product_id}-${idx}`}>
                    <td>
                      {l.product?.sku || products.find((p) => p.id === l.product_id)?.sku || l.product_id}
                      <div className="muted">
                        {l.product?.name ||
                          products.find((p) => p.id === l.product_id)?.name ||
                          editing.items.find((i) => i.product_id === l.product_id)?.product_name}
                      </div>
                    </td>
                    <td>
                      <input
                        type="number"
                        min="0.01"
                        step="1"
                        value={l.quantity}
                        onChange={(e) =>
                          setEditLines((prev) =>
                            prev.map((row, i) =>
                              i === idx ? { ...row, quantity: Number(e.target.value) } : row,
                            ),
                          )
                        }
                        style={{ width: 80 }}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={l.unit_cost}
                        onChange={(e) =>
                          setEditLines((prev) =>
                            prev.map((row, i) =>
                              i === idx ? { ...row, unit_cost: Number(e.target.value) } : row,
                            ),
                          )
                        }
                        style={{ width: 100 }}
                      />
                    </td>
                    <td>{peso(l.quantity * l.unit_cost)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn secondary"
                        onClick={() => setEditLines((prev) => prev.filter((_, i) => i !== idx))}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="toolbar" style={{ marginTop: '0.8rem' }}>
            <ProductSearchSelect
              products={products}
              value={editProductId ? Number(editProductId) : null}
              mode="purchase"
              onSelect={(id) => {
                setEditProductId(String(id))
                const p = products.find((x) => x.id === id)
                if (p) setEditCost(String(p.cost_price))
              }}
            />
            <input
              type="number"
              value={editQty}
              onChange={(e) => setEditQty(e.target.value)}
              style={{ width: 70 }}
              placeholder="Qty"
            />
            <input
              type="number"
              value={editCost}
              onChange={(e) => setEditCost(e.target.value)}
              style={{ width: 90 }}
              placeholder="Cost"
            />
            <button type="button" className="btn secondary" onClick={addEditLine}>
              Add item
            </button>
            <button type="button" className="btn" disabled={busy} onClick={saveEdit}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </div>

          <div style={{ marginTop: '1rem', paddingTop: '0.8rem', borderTop: '1px solid #e5e0d6' }}>
            <h2 style={{ marginTop: 0 }}>Receipt for this entry</h2>
            <p className="muted">Upload a photo or PDF of the supplier receipt for {editing.po_no}.</p>
            <div className="toolbar">
              <label className="btn secondary">
                {receiptBusy ? 'Uploading…' : 'Upload receipt'}
                <input
                  type="file"
                  accept="image/*,.pdf,application/pdf"
                  hidden
                  onChange={(e) => onReceiptUpload(editing.id, e.target.files?.[0] || null)}
                />
              </label>
              {editing.has_receipt && (
                <>
                  <a className="btn" href={api.purchaseReceiptUrl(editing.id)} target="_blank" rel="noreferrer">
                    View {editing.receipt_filename || 'receipt'}
                  </a>
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={async () => {
                      await api.deletePurchaseReceipt(editing.id)
                      const fresh = await api.getPurchase(editing.id)
                      setEditing(fresh)
                      load()
                      setOk('Receipt removed')
                    }}
                  >
                    Remove receipt
                  </button>
                </>
              )}
            </div>
            {editing.has_receipt && /\.(jpg|jpeg|png|webp|gif)$/i.test(editing.receipt_filename || '') && (
              <img
                src={api.purchaseReceiptUrl(editing.id)}
                alt="Receipt"
                style={{
                  marginTop: '0.75rem',
                  maxWidth: '100%',
                  maxHeight: 360,
                  objectFit: 'contain',
                  borderRadius: 8,
                  background: '#111',
                }}
              />
            )}
          </div>
        </div>
      )}

      <div className="panel" style={{ marginTop: '1rem' }}>
        <h2>Scan purchase invoice / delivery report</h2>
        <p className="muted">
          Upload a photo of a Quotation / Detailed Invoice Register or handwritten receiving list. Item Codes are
          matched to inventory SKUs — review qty, unit cost (Price), then post (stock increases). Multi-invoice pages
          create separate purchase entries.
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
                  alt="Purchase invoice scan"
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
                  Engine: {ocrPreview.engine}
                  {ocrPreview.document_type === 'invoice_register' ? ' · Invoice Register' : ''} ·{' '}
                  {ocrPreview.message}
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
                    <th>Date</th>
                    <th>Inv</th>
                    <th>Item code</th>
                    <th>Description</th>
                    <th>Select item</th>
                    <th>Qty</th>
                    <th>UOM</th>
                    <th>Unit cost</th>
                    <th>Amount</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {ocrRows.map((row, idx) => {
                    const amount =
                      row.line_amount != null
                        ? row.line_amount
                        : row.quantity && row.unit_price
                          ? Number(row.quantity) * Number(row.unit_price)
                          : null
                    return (
                      <tr key={`${row.row_number}-${idx}`}>
                        <td>
                          <input
                            type="checkbox"
                            checked={row.include !== false}
                            onChange={(e) => updateOcrRow(idx, { include: e.target.checked })}
                          />
                        </td>
                        <td>
                          <input
                            type="date"
                            value={row.sale_date ? String(row.sale_date).slice(0, 10) : ocrDate}
                            onChange={(e) => updateOcrRow(idx, { sale_date: e.target.value })}
                            style={{ width: 120 }}
                          />
                        </td>
                        <td>
                          <input
                            value={row.invoice_no || ''}
                            placeholder="Inv"
                            onChange={(e) => updateOcrRow(idx, { invoice_no: e.target.value })}
                            style={{ width: 90 }}
                          />
                        </td>
                        <td>
                          <input
                            value={row.sku || ''}
                            placeholder="Code"
                            onChange={(e) => updateOcrRow(idx, { sku: e.target.value })}
                            style={{ width: 110, fontFamily: 'ui-monospace, monospace' }}
                          />
                        </td>
                        <td style={{ minWidth: 140 }}>
                          <div className="muted" style={{ fontSize: '0.72rem' }}>
                            {row.ocr_text || '—'}
                          </div>
                          <input
                            value={row.product_name || ''}
                            placeholder="Description"
                            onChange={(e) => updateOcrRow(idx, { product_name: e.target.value })}
                          />
                        </td>
                        <td style={{ minWidth: 220 }}>
                          <ProductSearchSelect
                            products={products}
                            suggestions={row.suggestions || []}
                            value={row.matched_product_id}
                            selectedLabel={row.matched_product_name}
                            mode="purchase"
                            onSelect={(id) => selectProduct(idx, id)}
                          />
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
                            value={row.uom || ''}
                            placeholder="PCS"
                            onChange={(e) => updateOcrRow(idx, { uom: e.target.value })}
                            style={{ width: 56 }}
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
                        <td className="muted" style={{ whiteSpace: 'nowrap' }}>
                          {amount != null ? peso(amount) : '—'}
                        </td>
                        <td>
                          <span className="muted" style={{ fontSize: '0.75rem' }}>
                            {row.status || '—'}
                            {row.message ? (
                              <>
                                <br />
                                {row.message}
                              </>
                            ) : null}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
