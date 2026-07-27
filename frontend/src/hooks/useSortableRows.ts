import { useMemo, useState } from 'react'

export type SortDir = 'asc' | 'desc'

export function useSortableRows<T>(rows: T[], defaultKey: keyof T | string, defaultDir: SortDir = 'asc') {
  const [sortKey, setSortKey] = useState<string>(String(defaultKey))
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir)

  const sorted = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[sortKey]
      const bv = (b as unknown as Record<string, unknown>)[sortKey]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortDir === 'asc' ? av - bv : bv - av
      }
      const as = String(av).toLowerCase()
      const bs = String(bv).toLowerCase()
      if (as < bs) return sortDir === 'asc' ? -1 : 1
      if (as > bs) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return copy
  }, [rows, sortKey, sortDir])

  const toggle = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const indicator = (key: string) => (sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '')

  return { sorted, sortKey, sortDir, toggle, indicator }
}
