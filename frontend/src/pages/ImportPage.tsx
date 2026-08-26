import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type {
  ImportBatch,
  ImportPreview,
  ImportResult,
  OcrEditableRow,
  OcrPreview,
  Product,
  StockImportResult,
  StockPreview,
  WorkbookImportResult,
} from '../api'
import ProductSearchSelect from '../components/ProductSearchSelect'

type StockMode = 'set' | 'adjust' | 'upsert'

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [workbookResult, setWorkbookResult] = useState<WorkbookImportResult | null>(null)
  const [stockFile, setStockFile] = useState<File | null>(null)
  const [stockMode, setStockMode] = useState<StockMode>('set')
  const [stockPreview, setStockPreview] = useState<StockPreview | null>(null)
  const [stockResult, setStockResult] = useState<StockImportResult | null>(null)
  const [history, setHistory] = useState<ImportBatch[]>([])
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deductStock, setDeductStock] = useState(true)

  const [photoFile, setPhotoFile] = useState<File | null>(null)
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)
  const [ocrPreview, setOcrPreview] = useState<OcrPreview | null>(null)
  const [ocrRows, setOcrRows] = useState<OcrEditableRow[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [showRaw, setShowRaw] = useState(false)

  const [ocrStatus, setOcrStatus] = useState('')

  const loadHistory = () => api.imports().then(setHistory).catch((e) => setError(e.message))

  useEffect(() => {
    loadHistory()
    api.products().then(setProducts).catch(() => undefined)
  }, [])

  useEffect(() => {
    return () => {
      if (photoUrl) URL.revokeObjectURL(photoUrl)
    }
  }, [photoUrl])

  const isWorkbook = (f: File) => /\.xlsm?$/i.test(f.name) || /\.xls$/i.test(f.name)

  const onFile = async (f: File | null) => {
    setFile(f)
    setPreview(null)
    setResult(null)
    setWorkbookResult(null)
    setError('')
    if (!f) return
    if (/april|kygs|inventory/i.test(f.name) && isWorkbook(f)) {
      return
    }
    setBusy(true)
    try {
      const p = await api.previewImport(f)
      setPreview(p)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed')
    } finally {
      setBusy(false)
    }
  }

  const onPhoto = async (f: File | null) => {
    if (photoUrl) URL.revokeObjectURL(photoUrl)
    setPhotoFile(f)
    setPhotoUrl(f ? URL.createObjectURL(f) : null)
    setOcrPreview(null)
    setOcrRows([])
    setResult(null)
    setError('')
    setOcrStatus('')
    if (!f) return
    setBusy(true)
    setOcrStatus('Reading photo…')
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), 50000)
    try {
      const p = await api.previewSalesPhoto(f, ctrl.signal)
      setOcrPreview(p)
      setOcrRows(
        p.rows.map((r) => ({
          ...r,
          include: r.status !== 'blank',
          sale_date: r.sale_date ? String(r.sale_date).slice(0, 10) : '',
        })),
      )
      setOcrStatus(p.message || 'Done')
    } catch (err) {
      const msg =
        err instanceof Error && err.name === 'AbortError'
          ? 'OCR timed out. Try a smaller JPG or enter lines manually.'
          : err instanceof Error
            ? err.message
            : 'Photo OCR failed'
      setError(msg)
      // Still show blank editable rows so user is not stuck
      setOcrRows(
        Array.from({ length: 5 }, (_, i) => ({
          row_number: i + 1,
          quantity: 1,
          include: true,
          status: 'blank',
          sale_date: '',
          message: 'Enter manually',
        })),
      )
      setOcrStatus('')
    } finally {
      window.clearTimeout(timer)
      setBusy(false)
    }
  }

  const onStockFile = async (f: File | null, mode: StockMode = stockMode) => {
    setStockFile(f)
    setStockPreview(null)
    setStockResult(null)
    setError('')
    if (!f) return
    setBusy(true)
    try {
      const p = await api.previewStockImport(f, mode)
      setStockPreview(p)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Stock preview failed')
    } finally {
      setBusy(false)
    }
  }

  const updateOcrRow = (idx: number, patch: Partial<OcrEditableRow>) => {
    setOcrRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  const selectProduct = (idx: number, productId: number) => {
    const product = products.find((p) => p.id === productId)
    if (!product) return
    updateOcrRow(idx, {
      matched_product_id: product.id,
      matched_product_name: product.name,
      sku: product.sku,
      product_name: product.name,
      unit_price: ocrRows[idx].unit_price || product.sell_price,
      current_stock: product.stock_qty,
      status: 'matched',
      message: `Selected ${product.sku}`,
      include: true,
    })
  }

  const addBlankOcrRow = () => {
    setOcrRows((prev) => {
      const lastDate = [...prev].reverse().find((r) => r.sale_date)?.sale_date || ''
      return [
        ...prev,
        {
          row_number: (prev[prev.length - 1]?.row_number || 0) + 1,
          quantity: 1,
          include: true,
          status: 'blank',
          sale_date: lastDate,
          message: 'Manual line',
        },
      ]
    })
  }

  const applyDateToEmpty = (date: string) => {
    if (!date) return
    setOcrRows((prev) =>
      prev.map((r) => (r.sale_date ? r : { ...r, sale_date: date })),
    )
  }

  const fillMissingDatesFromAbove = () => {
    setOcrRows((prev) => {
      let last = ''
      return prev.map((r) => {
        const d = r.sale_date ? String(r.sale_date).slice(0, 10) : ''
        if (d) {
          last = d
          return r
        }
        return last ? { ...r, sale_date: last } : r
      })
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
    try {
      const r = await api.confirmSalesRows({
        filename: photoFile?.name || ocrPreview.filename,
        deduct_stock: deductStock,
        rows: ocrRows.map((row) => ({
          ...row,
          include: row.include !== false && !!row.matched_product_id && Number(row.quantity) > 0,
        })),
      })
      setResult(r)
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirm failed')
    } finally {
      setBusy(false)
    }
  }

  const runSalesImport = async () => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const r = await api.runImport(file, deductStock)
      setResult(r)
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  const runWorkbookUpload = async () => {
    if (!file) return
    setBusy(true)
    setError('')
    setWorkbookResult(null)
    try {
      const r = await api.importWorkbook(file, true)
      setWorkbookResult(r)
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Workbook import failed')
    } finally {
      setBusy(false)
    }
  }

  const runStockImport = async () => {
    if (!stockFile) return
    setBusy(true)
    setError('')
    try {
      const r = await api.runStockImport(stockFile, stockMode)
      setStockResult(r)
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Stock import failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Import / Stock Upload</h1>
          <p>
            Upload sales reports, handwritten photo scans, stock CSVs, or the full KYGS workbook.
          </p>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {result && (
        <div className="success-banner">
          {result.message}. Unmatched: {result.unmatched_skus.join(', ') || 'none'}
        </div>
      )}
      {workbookResult && (
        <div className="success-banner">
          {workbookResult.message}
          <div style={{ marginTop: '0.35rem' }}>
            Products {workbookResult.products_created} · Services {workbookResult.services_created} · Delisted{' '}
            {workbookResult.delisted_count} · Sales invoices {workbookResult.sales_created} (
            {workbookResult.sale_lines} lines)
          </div>
        </div>
      )}
      {stockResult && (
        <div className="success-banner">
          {stockResult.message}. Net qty change {stockResult.net_qty_change}. Unmatched:{' '}
          {stockResult.unmatched_skus.join(', ') || 'none'}
        </div>
      )}

      <div className="panel" style={{ marginBottom: '1rem' }}>
        <h2>Scan handwritten sales report (photo)</h2>
        <p className="muted">
          Take or upload a photo of a handwritten sales sheet. The app reads lines with OCR, then you correct
          qty/price/date and select the matching inventory item before saving.
        </p>
        <div className="toolbar">
          <input
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => onPhoto(e.target.files?.[0] || null)}
          />
          <label style={{ display: 'inline-flex', gap: '0.45rem', alignItems: 'center' }}>
            <input type="checkbox" checked={deductStock} onChange={(e) => setDeductStock(e.target.checked)} />
            Deduct stock on confirm
          </label>
          <button className="btn secondary" type="button" onClick={addBlankOcrRow} disabled={!ocrRows.length && !ocrPreview}>
            Add blank line
          </button>
          <button
            className="btn secondary"
            type="button"
            onClick={fillMissingDatesFromAbove}
            disabled={!ocrRows.length}
            title="Fill blank row dates from the nearest date above"
          >
            Fill missing dates
          </button>
          <button className="btn" disabled={busy || runnableOcrCount === 0} onClick={runOcrConfirm}>
            {busy ? ocrStatus || 'Working…' : `Confirm ${runnableOcrCount} line(s)`}
          </button>
        </div>
        {busy && (
          <p className="muted" style={{ marginTop: '0.5rem' }}>
            {ocrStatus || 'Working…'} This usually finishes in a few seconds. If it stalls, wait for timeout or
            refresh and try a smaller JPG.
          </p>
        )}
        {ocrRows.length > 0 && (
          <p className="muted" style={{ marginTop: '0.4rem' }}>
            Each line has its own sale date — multi-day sheets create separate sales per day.
            Unique dates:{' '}
            {Array.from(new Set(ocrRows.map((r) => (r.sale_date ? String(r.sale_date).slice(0, 10) : '')).filter(Boolean))).join(', ') ||
              'none yet'}
            . Quick set empty rows:{' '}
            <input
              type="date"
              onChange={(e) => applyDateToEmpty(e.target.value)}
              style={{ marginLeft: 4 }}
            />
          </p>
        )}

        {(photoUrl || ocrPreview) && (
          <div className="grid grid-2" style={{ marginTop: '1rem' }}>
            <div>
              {photoUrl && (
                <img
                  src={photoUrl}
                  alt="Sales report scan"
                  style={{ width: '100%', maxHeight: 420, objectFit: 'contain', borderRadius: 8, background: '#111' }}
                />
              )}
              {ocrPreview && (
                <p className="muted" style={{ marginTop: '0.6rem' }}>
                  Engine: {ocrPreview.engine} · {ocrPreview.message}
                  {ocrPreview.raw_text ? (
                    <>
                      {' '}
                      <button type="button" className="btn secondary" style={{ marginLeft: 8 }} onClick={() => setShowRaw((v) => !v)}>
                        {showRaw ? 'Hide OCR text' : 'Show OCR text'}
                      </button>
                    </>
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
                    <th>OCR / label</th>
                    <th>Select item</th>
                    <th>Qty</th>
                    <th>Price</th>
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
                      <td>
                        <input
                          type="date"
                          value={row.sale_date ? String(row.sale_date).slice(0, 10) : ''}
                          onChange={(e) => updateOcrRow(idx, { sale_date: e.target.value })}
                          style={{ minWidth: 130 }}
                        />
                      </td>
                      <td style={{ minWidth: 140 }}>
                        <div className="muted" style={{ fontSize: '0.75rem' }}>
                          {row.ocr_text || '—'}
                        </div>
                        <input
                          value={row.product_name || ''}
                          placeholder="Item text"
                          onChange={(e) => {
                            updateOcrRow(idx, { product_name: e.target.value })
                          }}
                          onBlur={async (e) => {
                            const label = e.target.value.trim()
                            if (!label || ocrRows[idx]?.matched_product_id) return
                            try {
                              const sug = await api.productSuggestions(label)
                              updateOcrRow(idx, { suggestions: sug })
                              if (sug[0] && sug[0].score >= 70) {
                                selectProduct(idx, sug[0].id)
                              }
                            } catch {
                              /* ignore */
                            }
                          }}
                        />
                        {row.message && (
                          <div className="muted" style={{ fontSize: '0.72rem' }}>
                            {row.message}
                          </div>
                        )}
                      </td>
                      <td style={{ minWidth: 220 }}>
                        <ProductSearchSelect
                          products={products}
                          suggestions={row.suggestions || []}
                          value={row.matched_product_id}
                          selectedLabel={row.matched_product_name}
                          mode="sale"
                          onSelect={(id) => selectProduct(idx, id)}
                        />
                        {row.matched_product_name && (
                          <div className="muted" style={{ fontSize: '0.72rem' }}>
                            {row.matched_product_name}
                            {row.current_stock != null ? ` · stock ${row.current_stock}` : ''}
                          </div>
                        )}
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

      <div className="panel" style={{ marginBottom: '1rem' }}>
        <h2>Stock CSV Upload</h2>
        <p className="muted">
          Manage inventory from CSV/Excel. Columns: <code>ITEM CODE</code>, <code>ENDING STOCKS</code> (or{' '}
          <code>QTY</code>), optional DESCRIPTION / UNIT PRICE / RETAIL PRICE / CATEGORY / SUPPLIER / ADJUST.
        </p>
        <div className="toolbar">
          {(['set', 'adjust', 'upsert'] as StockMode[]).map((m) => (
            <button
              key={m}
              className={`btn ${stockMode === m ? '' : 'secondary'}`}
              type="button"
              onClick={() => {
                setStockMode(m)
                if (stockFile) onStockFile(stockFile, m)
              }}
            >
              {m === 'set' ? 'Set stock' : m === 'adjust' ? 'Adjust (+/−)' : 'Upsert (create missing)'}
            </button>
          ))}
          <input
            type="file"
            accept=".csv,.xlsx,.xlsm,.xls"
            onChange={(e) => onStockFile(e.target.files?.[0] || null)}
          />
          <button
            className="btn"
            disabled={busy || !stockPreview || (stockPreview.matched_count === 0 && stockMode !== 'upsert')}
            onClick={runStockImport}
          >
            {busy ? 'Working…' : 'Apply stock file'}
          </button>
        </div>
        {stockPreview && (
          <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
            <p className="muted">
              Mode <strong>{stockPreview.mode}</strong> · matched {stockPreview.matched_count} · unmatched{' '}
              {stockPreview.unmatched_count} · will create {stockPreview.will_create_count}
            </p>
            <table>
              <thead>
                <tr>
                  <th>Row</th>
                  <th>SKU</th>
                  <th>Product</th>
                  <th>Current</th>
                  <th>New</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {stockPreview.rows.slice(0, 100).map((r) => (
                  <tr key={r.row_number}>
                    <td>{r.row_number}</td>
                    <td>{r.sku}</td>
                    <td>{r.product_name || '—'}</td>
                    <td>{r.current_stock ?? '—'}</td>
                    <td>{r.new_stock ?? '—'}</td>
                    <td>
                      <span
                        className={`badge ${r.status === 'matched' ? 'matched' : r.status === 'will_create' ? 'warn' : 'unmatched'}`}
                      >
                        {r.status}
                      </span>
                      <div className="muted" style={{ fontSize: '0.78rem' }}>
                        {r.message}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginBottom: '1rem' }}>
        <h2>Full KYGS Workbook</h2>
        <p className="muted">
          Upload a KYGS workbook to import INVENTORY ending stocks, SALES history, INFOSHEET,
          CRITICAL and DELISTED. Replaces current inventory/sales when replace is on. The shop's
          records live in this app's database — a workbook is only ever a one-off import.
        </p>
        <div className="toolbar">
          <label className="btn" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
            Upload .xlsm
            <input
              type="file"
              accept=".xlsm,.xlsx,.xls"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0] || null
                setFile(f)
                setPreview(null)
              }}
            />
          </label>
          {file && isWorkbook(file) && (
            <button className="btn" disabled={busy} onClick={runWorkbookUpload}>
              Import uploaded workbook
            </button>
          )}
        </div>
      </div>

      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDrag(false)
          const f = e.dataTransfer.files?.[0]
          if (f) {
            if (f.type.startsWith('image/')) onPhoto(f)
            else onFile(f)
          }
        }}
      >
        <p style={{ marginTop: 0, fontFamily: 'Oswald, sans-serif', fontSize: '1.3rem', letterSpacing: '0.04em' }}>
          DROP SALES CSV / PHOTO HERE
        </p>
        <p className="muted">
          Accepts KYGS SALES exports (.csv / .xlsx / .xlsm) or a photo of a handwritten report.
        </p>
        <input
          type="file"
          accept=".csv,.xlsx,.xlsm,.xls,image/*"
          onChange={(e) => {
            const f = e.target.files?.[0] || null
            if (f?.type.startsWith('image/')) onPhoto(f)
            else onFile(f)
          }}
        />
      </div>

      {preview && (
        <div className="panel" style={{ marginTop: '1rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
            <div>
              <h2 style={{ marginBottom: '0.3rem' }}>Preview — {preview.filename}</h2>
              <p className="muted" style={{ margin: 0 }}>
                Matched {preview.matched_count} · Unmatched {preview.unmatched_count} · Qty {preview.total_qty}
              </p>
              <label style={{ display: 'inline-flex', gap: '0.45rem', marginTop: '0.6rem', alignItems: 'center' }}>
                <input type="checkbox" checked={deductStock} onChange={(e) => setDeductStock(e.target.checked)} />
                Deduct stock on import (turn off if stocks already reflect these sales)
              </label>
            </div>
            <button className="btn" disabled={busy || preview.matched_count === 0} onClick={runSalesImport}>
              {busy ? 'Working…' : deductStock ? 'Import & Deduct Stock' : 'Import Sales Only'}
            </button>
          </div>
          <div className="table-wrap" style={{ marginTop: '1rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Invoice</th>
                  <th>Date</th>
                  <th>SKU / Product</th>
                  <th>Qty</th>
                  <th>Match</th>
                  <th>Stock Now</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row_number}>
                    <td>{r.row_number}</td>
                    <td>{r.invoice_no || '—'}</td>
                    <td>{r.sale_date ? String(r.sale_date).slice(0, 10) : '—'}</td>
                    <td>
                      {r.sku || '—'}
                      <div className="muted">{r.product_name}</div>
                    </td>
                    <td>{r.quantity ?? '—'}</td>
                    <td>{r.matched_product_name || '—'}</td>
                    <td>{r.current_stock ?? '—'}</td>
                    <td>
                      <span className={`badge ${r.status}`}>{r.status}</span>
                      <div className="muted" style={{ fontSize: '0.78rem' }}>
                        {r.message}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="panel" style={{ marginTop: '1rem' }}>
        <h2>Import History</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>File</th>
                <th>Imported</th>
                <th>Skipped</th>
                <th>Stock Deducted</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td>{new Date(h.created_at).toLocaleString()}</td>
                  <td>{h.filename}</td>
                  <td>{h.rows_imported}</td>
                  <td>{h.rows_skipped}</td>
                  <td>{h.stock_deducted}</td>
                  <td>{h.summary}</td>
                </tr>
              ))}
              {!history.length && (
                <tr>
                  <td colSpan={6} className="muted">
                    No imports yet.
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
