import { useEffect, useMemo, useRef, useState } from 'react'
import { peso } from '../api'
import type { OcrSuggestion, Product } from '../api'

type Props = {
  products: Product[]
  suggestions?: OcrSuggestion[]
  value?: number | null
  selectedLabel?: string | null
  mode?: 'sale' | 'purchase'
  onSelect: (productId: number) => void
}

/** Searchable inventory picker for OCR review rows. */
export default function ProductSearchSelect({
  products,
  suggestions = [],
  value,
  selectedLabel,
  mode = 'sale',
  onSelect,
}: Props) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const selected = useMemo(
    () => (value ? products.find((p) => p.id === value) : undefined),
    [products, value],
  )

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase()
    const sugIds = new Set(suggestions.map((s) => s.id))
    let list = products
    if (query) {
      const qCompact = query.replace(/[\s\-_]/g, '')
      list = products
        .map((p) => {
          const sku = p.sku.toLowerCase()
          const skuCompact = sku.replace(/[\s\-_]/g, '')
          const name = p.name.toLowerCase()
          const brand = (p.brand || '').toLowerCase()
          const fitment = (p.fitment || '').toLowerCase()
          let rank = 0
          if (sku === query || skuCompact === qCompact) rank = 100
          else if (sku.startsWith(query) || skuCompact.startsWith(qCompact)) rank = 90
          else if (sku.includes(query) || skuCompact.includes(qCompact)) rank = 80
          else if (name.includes(query)) rank = 60
          else if (brand.includes(query) || fitment.includes(query)) rank = 40
          else rank = 0
          return { p, rank }
        })
        .filter((x) => x.rank > 0)
        .sort((a, b) => b.rank - a.rank || a.p.sku.localeCompare(b.p.sku))
        .map((x) => x.p)
    }
    // Prefer suggestions first when no query
    if (!query && suggestions.length) {
      const sugProducts = suggestions
        .map((s) => products.find((p) => p.id === s.id))
        .filter(Boolean) as Product[]
      const rest = list.filter((p) => !sugIds.has(p.id))
      return [...sugProducts, ...rest].slice(0, 80)
    }
    return list.slice(0, 80)
  }, [products, q, suggestions])

  const display = selected
    ? `${selected.sku} — ${selected.name}`
    : selectedLabel || ''

  return (
    <div ref={rootRef} style={{ position: 'relative', minWidth: 220 }}>
      <input
        value={open ? q : display}
        placeholder="Search SKU / name…"
        onFocus={() => {
          setOpen(true)
          setQ('')
        }}
        onChange={(e) => {
          setQ(e.target.value)
          setOpen(true)
        }}
        style={{ width: '100%' }}
      />
      {open && (
        <div
          style={{
            position: 'absolute',
            zIndex: 40,
            left: 0,
            right: 0,
            top: '100%',
            maxHeight: 220,
            overflow: 'auto',
            background: '#fff',
            border: '1px solid #d5d0c4',
            borderRadius: 6,
            boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
          }}
        >
          {!filtered.length && (
            <div className="muted" style={{ padding: '0.55rem 0.7rem', fontSize: '0.85rem' }}>
              No inventory match
            </div>
          )}
          {filtered.map((p) => {
            const sug = suggestions.find((s) => s.id === p.id)
            const price = mode === 'purchase' ? p.cost_price : p.sell_price
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  onSelect(p.id)
                  setOpen(false)
                  setQ('')
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  border: 0,
                  background: value === p.id ? '#f4f1ea' : 'transparent',
                  padding: '0.45rem 0.7rem',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                }}
              >
                {sug ? '★ ' : ''}
                <strong>{p.sku}</strong> — {p.name}
                <div className="muted" style={{ fontSize: '0.72rem' }}>
                  {peso(price)} · stock {p.stock_qty}
                  {sug ? ` · match ${sug.score}` : ''}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
