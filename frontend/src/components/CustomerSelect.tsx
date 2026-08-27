import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { Customer } from '../api'

type Props = {
  customers: Customer[]
  value: number | null
  /** Free-text name for a walk-in who is not (yet) a saved customer. */
  walkInName?: string
  onSelect: (customer: Customer | null) => void
  onWalkInName?: (name: string) => void
  /** Called after a new customer record is created here. */
  onCreated?: (customer: Customer) => void
  allowWalkIn?: boolean
}

/** Searchable customer picker with inline "add new" — so the counter never has
 *  to leave the till to record a first-time rider. */
export default function CustomerSelect({
  customers, value, walkInName = '', onSelect, onWalkInName, onCreated,
  allowWalkIn = true,
}: Props) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState({ name: '', phone: '', motorcycle_model: '', address: '' })
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // Choosing an option unmounts it, and the browser then restores focus to the
  // input. Without this guard that refocus reopens the list and blanks the text
  // the user just picked.
  const justPickedRef = useRef(false)

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const selected = useMemo(
    () => customers.find((c) => c.id === value) || null,
    [customers, value],
  )

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase()
    if (!term) return customers.slice(0, 30)
    return customers
      .filter((c) =>
        c.name.toLowerCase().includes(term)
        || (c.phone || '').toLowerCase().includes(term)
        || (c.motorcycle_model || '').toLowerCase().includes(term))
      .slice(0, 30)
  }, [customers, q])

  const display = selected
    ? `${selected.name}${selected.motorcycle_model ? ` — ${selected.motorcycle_model}` : ''}`
    : walkInName

  /** Commit a choice and close, immune to the focus bounce described above. */
  const choose = (customer: Customer | null) => {
    justPickedRef.current = true
    onSelect(customer)
    setQ('')
    setOpen(false)
    inputRef.current?.blur()
  }

  const createCustomer = async () => {
    if (!draft.name.trim()) {
      setError('A name is required')
      return
    }
    setBusy(true)
    setError('')
    try {
      const created = await api.createCustomer({
        name: draft.name.trim(),
        phone: draft.phone.trim() || undefined,
        motorcycle_model: draft.motorcycle_model.trim() || undefined,
        address: draft.address.trim() || undefined,
      })
      onCreated?.(created)
      setAdding(false)
      choose(created)
      setDraft({ name: '', phone: '', motorcycle_model: '', address: '' })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the customer')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div ref={rootRef} style={{ position: 'relative', minWidth: 240 }}>
      <input
        ref={inputRef}
        value={open ? q : display}
        placeholder="Search customer, phone or bike…"
        onFocus={() => {
          if (justPickedRef.current) {
            justPickedRef.current = false
            return
          }
          setOpen(true)
          setQ('')
        }}
        onChange={(e) => {
          setQ(e.target.value)
          setOpen(true)
          // Typing a name that is not on file still records the walk-in.
          if (allowWalkIn) onWalkInName?.(e.target.value)
        }}
        style={{ width: '100%' }}
      />

      {open && (
        <div
          style={{
            position: 'absolute', zIndex: 40, left: 0, right: 0, top: '100%',
            maxHeight: 300, overflow: 'auto', background: 'var(--surface-2)',
            border: '1px solid var(--line)', borderRadius: 6,
            boxShadow: 'var(--shadow)',
          }}
        >
          {adding ? (
            <div style={{ padding: '0.7rem' }}>
              <div className="label" style={{ marginBottom: '0.4rem' }}>New customer</div>
              <input placeholder="Name" value={draft.name} autoFocus
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                     style={{ width: '100%', marginBottom: '0.4rem' }} />
              <input placeholder="Phone" value={draft.phone}
                     onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
                     style={{ width: '100%', marginBottom: '0.4rem' }} />
              <input placeholder="Motorcycle model" value={draft.motorcycle_model}
                     onChange={(e) => setDraft({ ...draft, motorcycle_model: e.target.value })}
                     style={{ width: '100%', marginBottom: '0.4rem' }} />
              <input placeholder="Address" value={draft.address}
                     onChange={(e) => setDraft({ ...draft, address: e.target.value })}
                     style={{ width: '100%', marginBottom: '0.5rem' }} />
              {error && <div className="error-banner">{error}</div>}
              <div className="toolbar">
                <button type="button" className="btn" disabled={busy}
                        onClick={createCustomer}>Save customer</button>
                <button type="button" className="btn secondary"
                        onClick={() => { setAdding(false); setError('') }}>Back</button>
              </div>
            </div>
          ) : (
            <>
              {allowWalkIn && (
                <button type="button"
                        onClick={() => choose(null)}
                        style={optionStyle}>
                  <span className="muted">Walk-in (no saved record)</span>
                </button>
              )}
              {filtered.map((c) => (
                <button key={c.id} type="button"
                        onClick={() => choose(c)}
                        style={optionStyle}>
                  <div>{c.name}</div>
                  <div className="muted" style={{ fontSize: '0.72rem' }}>
                    {[c.phone, c.motorcycle_model].filter(Boolean).join(' · ') || '—'}
                  </div>
                </button>
              ))}
              {!filtered.length && (
                <div className="muted" style={{ padding: '0.55rem 0.7rem', fontSize: '0.85rem' }}>
                  No customer match
                </div>
              )}
              <button type="button"
                      onClick={() => {
                        setAdding(true)
                        setDraft({ name: q.trim(), phone: '', motorcycle_model: '', address: '' })
                      }}
                      style={{ ...optionStyle, borderTop: '1px solid var(--line)' }}>
                <strong>+ Add new customer{q.trim() ? ` “${q.trim()}”` : ''}</strong>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

const optionStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  padding: '0.5rem 0.7rem',
  background: 'none',
  border: 0,
  cursor: 'pointer',
}
