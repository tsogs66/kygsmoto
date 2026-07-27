import { useEffect, useState } from 'react'
import { api } from '../api'
import type {
  ImportBatch,
  ImportPreview,
  ImportResult,
  StockImportResult,
  StockPreview,
  WorkbookImportResult,
} from '../api'

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

  const loadHistory = () => api.imports().then(setHistory).catch((e) => setError(e.message))

  useEffect(() => {
    loadHistory()
  }, [])

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

  const runLocalWorkbook = async () => {
    setBusy(true)
    setError('')
    setWorkbookResult(null)
    try {
      const r = await api.importWorkbookLocal('KYGS APRIL 2025.xlsm', true)
      setWorkbookResult(r)
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Local workbook import failed')
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
            Upload sales reports, stock CSVs, or the full KYGS workbook. Extracted samples live in{' '}
            <code>samples/kygs_current_inventory.csv</code> and <code>samples/kygs_sales_export.csv</code>.
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
        <h2>Stock CSV Upload</h2>
        <p className="muted">
          Manage inventory from CSV/Excel. Columns: <code>ITEM CODE</code>, <code>ENDING STOCKS</code> (or{' '}
          <code>QTY</code>), optional DESCRIPTION / UNIT PRICE / RETAIL PRICE / CATEGORY / SUPPLIER / ADJUST.
          Sample: <code>samples/kygs_stock_upload_template.csv</code> or full{' '}
          <code>samples/kygs_current_inventory.csv</code>.
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
                      <span className={`badge ${r.status === 'matched' ? 'matched' : r.status === 'will_create' ? 'warn' : 'unmatched'}`}>
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
            {stockPreview.rows.length > 100 && (
              <p className="muted">Showing first 100 of {stockPreview.rows.length} rows</p>
            )}
          </div>
        )}
      </div>

      <div className="panel" style={{ marginBottom: '1rem' }}>
        <h2>Full KYGS Workbook</h2>
        <p className="muted">
          Imports INVENTORY ending stocks (no double-deduction), SALES history, INFOSHEET services/categories/suppliers,
          CRITICAL reorder margins, and DELISTED products. Replaces current demo/seed data.
        </p>
        <div className="toolbar">
          <button className="btn" disabled={busy} onClick={runLocalWorkbook}>
            {busy ? 'Importing…' : 'Import KYGS APRIL 2025.xlsm from server'}
          </button>
          <label className="btn secondary" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
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
          if (f) onFile(f)
        }}
      >
        <p style={{ marginTop: 0, fontFamily: 'Oswald, sans-serif', fontSize: '1.3rem', letterSpacing: '0.04em' }}>
          DROP SALES REPORT / CSV HERE
        </p>
        <p className="muted">
          Accepts KYGS SALES sheet exports (.csv / .xlsx / .xlsm). Auto-selects the SALES sheet inside workbooks.
          Sample: <code>samples/kygs_sales_export.csv</code>
        </p>
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
