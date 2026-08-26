import { useEffect, useState } from 'react'
import { api, peso } from '../api'
import type { Customer, Job, JobBoard, Product } from '../api'
import ProductSearchSelect from '../components/ProductSearchSelect'
import CustomerSelect from '../components/CustomerSelect'

const STATUS_LABEL: Record<string, string> = {
  queued: 'Waiting',
  in_progress: 'In progress',
  ready: 'Ready for release',
  completed: 'Completed',
  cancelled: 'Cancelled',
}
const NEXT_STATUS: Record<string, string> = { queued: 'in_progress', in_progress: 'ready' }
const NEXT_LABEL: Record<string, string> = { queued: 'Start work', in_progress: 'Mark ready' }

export default function JobQueuePage() {
  const [board, setBoard] = useState<JobBoard | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [filter, setFilter] = useState('open')
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<Job | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [customerId, setCustomerId] = useState<number | null>(null)
  const [saveCustomer, setSaveCustomer] = useState(false)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)

  // New ticket form
  const [showNew, setShowNew] = useState(false)
  const [form, setForm] = useState({
    customer_name: '', contact: '', plate_no: '', motorcycle: '',
    complaint: '', mechanic: '', priority: 'normal',
  })

  // Add-work picker on the open ticket
  const [addProductId, setAddProductId] = useState('')
  const [addQty, setAddQty] = useState('1')
  const [addDiscount, setAddDiscount] = useState('0')

  const load = async () => {
    setError('')
    try {
      const [b, list] = await Promise.all([api.jobBoard(), api.jobs(filter, search)])
      setBoard(b)
      setJobs(list.jobs)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the queue')
    }
  }

  useEffect(() => {
    load()
    api.products().then(setProducts).catch(() => undefined)
    api.customers().then(setCustomers).catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  const refreshDetail = async (id: number) => {
    setDetail(await api.job(id))
    load()
  }

  const createJob = async () => {
    setBusy(true)
    setError('')
    try {
      const job = await api.createJob({
        ...form,
        customer_id: customerId,
        save_customer: customerId ? false : saveCustomer,
      })
      setOk(`${job.job_no} opened`)
      setShowNew(false)
      setCustomerId(null)
      setSaveCustomer(false)
      setForm({ customer_name: '', contact: '', plate_no: '', motorcycle: '',
                complaint: '', mechanic: '', priority: 'normal' })
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open the job')
    } finally {
      setBusy(false)
    }
  }

  const advance = async (job: Job) => {
    const next = NEXT_STATUS[job.status]
    if (!next) return
    try {
      await api.updateJob(job.id, { status: next })
      setOk(`${job.job_no} → ${STATUS_LABEL[next]}`)
      refreshDetail(job.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update')
    }
  }

  const addWork = async () => {
    if (!detail || !addProductId) return
    try {
      await api.addJobLine(detail.id, Number(addProductId), Number(addQty) || 1,
                           Math.max(0, Number(addDiscount) || 0))
      setAddProductId('')
      setAddQty('1')
      setAddDiscount('0')
      refreshDetail(detail.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not add work')
    }
  }

  const checkout = async (job: Job, allowNegative = false) => {
    // Selling past what is on the shelf drives stock negative, so make the
    // operator confirm it rather than letting one click do it quietly.
    if (allowNegative) {
      const short = job.lines.filter((l) => l.short).map((l) => l.product_name)
      const proceed = window.confirm(
        `Not enough stock for: ${short.join(', ')}.\n\n` +
        'Taking payment will leave stock negative until the delivery is booked in. Continue?',
      )
      if (!proceed) return
    }
    setBusy(true)
    setError('')
    try {
      const res = await api.checkoutJob(job.id, { allow_negative_stock: allowNegative })
      setOk(`${job.job_no} completed — invoice ${res.sale.invoice_no}`)
      setDetail(null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not take payment')
    } finally {
      setBusy(false)
    }
  }

  const cancel = async (job: Job) => {
    const reason = window.prompt('Why is this job being cancelled?')
    if (!reason || reason.trim().length < 3) return
    try {
      await api.cancelJob(job.id, reason.trim())
      setOk(`${job.job_no} cancelled`)
      setDetail(null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not cancel')
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Job Queue</h1>
          <p className="muted">
            Bikes in the shop: what is waiting, in progress and ready for release.
          </p>
        </div>
        <div className="toolbar">
          <button className="btn" onClick={() => setShowNew((v) => !v)}>
            {showNew ? 'Close' : 'New job ticket'}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {ok && <div className="muted">{ok}</div>}

      {board && (
        <div className="grid grid-4">
          <div className="panel stat">
            <div className="label">Waiting</div>
            <div className="value">{board.counts.queued || 0}</div>
          </div>
          <div className="panel stat">
            <div className="label">In progress</div>
            <div className="value">{board.counts.in_progress || 0}</div>
          </div>
          <div className="panel stat">
            <div className="label">Ready for release</div>
            <div className="value">{board.counts.ready || 0}</div>
          </div>
          <div className="panel stat">
            <div className="label">Value in the shop</div>
            <div className="value">{peso(board.open_value)}</div>
            <div className="muted">{board.open_total} open job(s)</div>
          </div>
        </div>
      )}

      {showNew && (
        <div className="panel" style={{ marginTop: '1rem' }}>
          <h2>New job ticket</h2>
          <div className="grid grid-2">
            <label className="label">Customer
              <CustomerSelect
                customers={customers}
                value={customerId}
                walkInName={form.customer_name}
                onSelect={(c) => {
                  setCustomerId(c ? c.id : null)
                  if (c) {
                    // Pull what we already know about this rider onto the ticket.
                    setForm((f) => ({
                      ...f,
                      customer_name: c.name,
                      contact: c.phone || f.contact,
                      motorcycle: c.motorcycle_model || f.motorcycle,
                    }))
                    setSaveCustomer(false)
                  }
                }}
                onWalkInName={(name) => setForm((f) => ({ ...f, customer_name: name }))}
                onCreated={(c) => setCustomers((prev) => [...prev, c])}
              />
            </label>
            <label className="label">Contact number
              <input value={form.contact}
                     onChange={(e) => setForm({ ...form, contact: e.target.value })} />
            </label>
            <label className="label">Plate number
              <input value={form.plate_no}
                     onChange={(e) => setForm({ ...form, plate_no: e.target.value })} />
            </label>
            <label className="label">Motorcycle model
              <input placeholder="e.g. Mio i125, NMAX, TMX" value={form.motorcycle}
                     onChange={(e) => setForm({ ...form, motorcycle: e.target.value })} />
            </label>
            <label className="label">Mechanic
              <input value={form.mechanic}
                     onChange={(e) => setForm({ ...form, mechanic: e.target.value })} />
            </label>
            <label className="label">Priority
              <select value={form.priority}
                      onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                <option value="normal">Normal</option>
                <option value="urgent">Urgent</option>
              </select>
            </label>
          </div>
          {!customerId && form.customer_name.trim() && (
            <label className="label" style={{ display: 'flex', gap: '0.5rem',
                                              alignItems: 'center' }}>
              <input type="checkbox" checked={saveCustomer} style={{ width: 'auto' }}
                     onChange={(e) => setSaveCustomer(e.target.checked)} />
              <span>Save “{form.customer_name.trim()}” as a customer for next time</span>
            </label>
          )}
          <label className="label">Reported problem
            <input placeholder="What did the customer bring it in for?" value={form.complaint}
                   onChange={(e) => setForm({ ...form, complaint: e.target.value })} />
          </label>
          <button className="btn" disabled={busy} onClick={createJob}>Open job</button>
        </div>
      )}

      <div className="toolbar" style={{ margin: '1rem 0' }}>
        <label className="label">Show
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="open">Open jobs</option>
            <option value="queued">Waiting</option>
            <option value="in_progress">In progress</option>
            <option value="ready">Ready for release</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        <label className="label">Search
          <input value={search} placeholder="Job no, customer, plate or model"
                 onChange={(e) => setSearch(e.target.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') load() }} />
        </label>
        <button className="btn secondary" onClick={load}>Refresh</button>
      </div>

      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th><th>Customer</th><th>Complaint</th><th>Status</th>
                <th>Mechanic</th><th className="num">Lines</th>
                <th className="num">Value</th><th className="num">Waiting</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} style={{ cursor: 'pointer' }}
                    onClick={() => setDetail(job)}>
                  <td>
                    <strong>{job.job_no}</strong>
                    {job.priority === 'urgent' && <span className="muted"> · urgent</span>}
                  </td>
                  <td>
                    {job.customer_name || '—'}
                    <div className="muted">{job.plate_no} {job.motorcycle}</div>
                  </td>
                  <td className="muted">{job.complaint.slice(0, 46)}</td>
                  <td>{STATUS_LABEL[job.status] || job.status}</td>
                  <td className="muted">{job.mechanic || 'unassigned'}</td>
                  <td className="num">{job.line_count}</td>
                  <td className="num">{peso(job.total)}</td>
                  <td className="num">{job.hours_open ?? 0}h</td>
                </tr>
              ))}
              {!jobs.length && (
                <tr><td colSpan={8} className="muted">No jobs here.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detail && (
        <div className="backdrop" onClick={() => setDetail(null)}>
          <div className="panel modal" onClick={(e) => e.stopPropagation()}
               style={{ maxWidth: 880, margin: '4vh auto', maxHeight: '88vh', overflowY: 'auto' }}>
            <div className="page-header">
              <div>
                <h2>{detail.job_no} — {detail.customer_name || 'Walk-in'}</h2>
                <p className="muted">
                  {detail.motorcycle} {detail.plate_no} · {STATUS_LABEL[detail.status]}
                  {detail.mechanic && ` · ${detail.mechanic}`}
                </p>
              </div>
              <button className="btn secondary" onClick={() => setDetail(null)}>Close</button>
            </div>

            {detail.complaint && (
              <p><strong>Reported:</strong> {detail.complaint}</p>
            )}
            {detail.short_lines > 0 && (
              <div className="error-banner">
                {detail.short_lines} line(s) need more stock than is on the shelf.
                Receive stock, reduce the line, or confirm to sell anyway.
              </div>
            )}
            {detail.invoice_no && (
              <p className="muted">Paid on invoice <strong>{detail.invoice_no}</strong></p>
            )}
            {detail.status === 'cancelled' && (
              <div className="error-banner">Cancelled: {detail.cancel_reason}</div>
            )}

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Type</th><th>Description</th><th className="num">Qty</th>
                    <th className="num">Price</th><th className="num">Less</th>
                    <th className="num">Total</th><th />
                  </tr>
                </thead>
                <tbody>
                  {detail.lines.map((line) => (
                    <tr key={line.id}>
                      <td>{line.is_labour ? 'Labour' : 'Part'}</td>
                      <td>
                        {line.product_name}
                        {line.short && <span className="muted"> · short</span>}
                        <div className="muted">{line.sku}</div>
                      </td>
                      <td className="num">{line.quantity}</td>
                      <td className="num">{peso(line.unit_price)}</td>
                      <td className="num">{line.discount ? peso(line.discount) : '—'}</td>
                      <td className="num">{peso(line.line_total)}</td>
                      <td>
                        {['queued', 'in_progress', 'ready'].includes(detail.status) && (
                          <button className="btn secondary"
                                  onClick={async () => {
                                    await api.removeJobLine(detail.id, line.id)
                                    refreshDetail(detail.id)
                                  }}>Remove</button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!detail.lines.length && (
                    <tr><td colSpan={7} className="muted">No parts or labour yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <p><strong>Parts</strong> {peso(detail.parts_total)} ·{' '}
               <strong>Labour</strong> {peso(detail.labour_total)}
               {detail.discount_total > 0 && (
                 <> · <strong>Discounts</strong> {peso(detail.discount_total)}</>
               )} ·{' '}
               <strong>Total</strong> {peso(detail.total)}</p>

            {['queued', 'in_progress', 'ready'].includes(detail.status) && (
              <>
                <h3>Add work</h3>
                <div className="toolbar">
                  <ProductSearchSelect products={products}
                                       value={addProductId ? Number(addProductId) : null}
                                       onSelect={(id) => setAddProductId(String(id))} />
                  <input type="number" min="1" step="1" value={addQty} style={{ width: 80 }}
                         title="Quantity"
                         onChange={(e) => setAddQty(e.target.value)} />
                  <input type="number" min="0" step="0.01" value={addDiscount}
                         style={{ width: 90 }} title="Discount on this line"
                         onChange={(e) => setAddDiscount(e.target.value)} />
                  <button className="btn secondary" onClick={addWork}>Add</button>
                </div>

                <div className="toolbar" style={{ marginTop: '1rem' }}>
                  {NEXT_STATUS[detail.status] && (
                    <button className="btn secondary" onClick={() => advance(detail)}>
                      {NEXT_LABEL[detail.status]}
                    </button>
                  )}
                  <button className="btn" disabled={busy}
                          onClick={() => checkout(detail, detail.short_lines > 0)}>
                    {detail.short_lines > 0 ? 'Take payment anyway' : 'Take payment'}
                  </button>
                  <button className="btn secondary" onClick={() => cancel(detail)}>
                    Cancel job
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
