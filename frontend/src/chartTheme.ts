/**
 * One place for what the charts are allowed to look like.
 *
 * Recharts paints its own defaults — mid-grey ticks, a white tooltip — which
 * were invisible against the slate ground once the palette moved. These are
 * the values every chart on the site reads, so a future palette change is one
 * file rather than a hunt through pages.
 */

export const CHART_GRID = '#2c3846'
export const CHART_TICK = { fontSize: 11, fill: '#8b9bb0' }
export const CHART_TICK_LG = { fontSize: 12, fill: '#8b9bb0' }
export const CHART_AXIS_LINE = '#2c3846'

/** Series colours, ordered so neighbours stay distinguishable. */
export const CHART_COLORS = [
  '#ff6b35',
  '#3d9df5',
  '#35c77a',
  '#f5b93d',
  '#a78bfa',
  '#f2564c',
]

export const CHART_ACCENT = CHART_COLORS[0]
export const CHART_SECONDARY = CHART_COLORS[1]
export const CHART_OK = CHART_COLORS[2]

/** Tooltip chrome: a raised card, not a white box punched in the dark. */
export const CHART_TOOLTIP = {
  contentStyle: {
    background: '#1e2733',
    border: '1px solid #2c3846',
    borderRadius: 10,
    color: '#e6edf3',
  },
  labelStyle: { color: '#8b9bb0' },
  itemStyle: { color: '#e6edf3' },
  cursor: { fill: 'rgba(255, 107, 53, 0.08)' },
}
