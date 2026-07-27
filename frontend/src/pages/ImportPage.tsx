import { useEffect, useState } from 'react'
import { api } from '../api'
import type { ImportBatch, ImportPreview, ImportResult } from '../api'

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [history, setHistory] = useState<ImportBatch[]>([])
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const loadHistory = () => api.imports().then(setHistory).catch((e) => setError(e.message))

  useEffect(() => {
    loadHistory()
  }, [])

  const onFile = async (f: File | null) => {
    setFile(f)
    setPreview(null)
    setResult(null)
    setError('')
    if (!f) return
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

  const runImport = async () => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const r = await api.runImport(file, true)
      setResult(r)
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Sales File Import</h1>
          <p>
            Upload CSV/Excel sales reports — the system matches SKUs/products and deducts sold quantities from
            inventory stock.
          </p>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {result && (
        <div className="success-banner">
          {result.message}. Unmatched: {result.unmatched_skus.join(', ') || 'none'}
        </div>
      )}

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
          if (f) onFile(f)
        }}
      >
        <p style={{ marginTop: 0, fontFamily: 'Oswald, sans-serif', fontSize: '1.3rem', letterSpacing: '0.04em' }}>
          DROP SALES REPORT HERE
        </p>
        <p className="muted">Accepts .csv / .xlsx / .xlsm — columns like Invoice, Date, SKU, Product, Qty, Price</p>
        <input
          type="file"
          accept=".csv,.xlsx,.xlsm,.xls"
          onChange={(e) => onFile(e.target.files?.[0] || null)}
        />
      </div>

      {preview && (
        <div className="panel" style={{ marginTop: '1rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
            <div>
              <h2 style={{ marginBottom: '0.3rem' }}>Preview — {preview.filename}</h2>
              <p className="muted" style={{ margin: 0 }}>
                Matched {preview.matched_count} · Unmatched {preview.unmatched_count} · Qty to deduct{' '}
                {preview.total_qty}
              </p>
            </div>
            <button className="btn" disabled={busy || preview.matched_count === 0} onClick={runImport}>
              {busy ? 'Working…' : 'Import & Deduct Stock'}
            </button>
          </div>
          <div className="table-wrap" style={{ marginTop: '1rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Invoice</th>
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
                    No imports yet. Try samples/sample_sales_import.csv
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
