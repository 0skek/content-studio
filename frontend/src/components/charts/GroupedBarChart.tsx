import { useId, useRef, useState, type FocusEvent, type PointerEvent } from 'react'

// A grouped horizontal bar chart following the dataviz mark specs: thin bars (14px) with a 4px rounded data end,
// a 2px gap between neighbouring bars, the value at every bar tip (few bars, so labels never crowd), a legend for
// two or more series, a hover/focus tooltip that only repeats what is visible, and a table-view twin.

export interface ChartSeries {
  key: string
  label: string
  // A CSS colour, normally a var(--series-N) token.
  color: string
}

export interface ChartCategory {
  key: string
  label: string
}

export interface ChartValue {
  value: number
  // Extra context for the tooltip and table, e.g. "2 posts · 6,200 impressions".
  detail: string
}

interface GroupedBarChartProps {
  title: string
  subtitle: string
  categories: ChartCategory[]
  series: ChartSeries[]
  valueOf: (categoryKey: string, seriesKey: string) => ChartValue | null
  format: (value: number) => string
  emptyLabel?: string
}

interface Tooltip {
  x: number
  y: number
  value: string
  series: string
  category: string
  detail: string
}

// Bars use at most this share of the track, leaving room for the value label at the tip.
const MAX_BAR_SHARE = 0.82
const TOOLTIP_OFFSET_PX = 12

export function GroupedBarChart({
  title,
  subtitle,
  categories,
  series,
  valueOf,
  format,
  emptyLabel = 'no posts',
}: GroupedBarChartProps) {
  const [showTable, setShowTable] = useState(false)
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const figureRef = useRef<HTMLElement>(null)
  const titleId = useId()

  const values = categories.flatMap((category) =>
    series.map((entry) => valueOf(category.key, entry.key)?.value ?? 0),
  )
  const maxValue = Math.max(...values, Number.EPSILON)

  function tooltipFor(categoryLabel: string, entry: ChartSeries, datum: ChartValue, x: number, y: number): Tooltip {
    return { x, y, value: format(datum.value), series: entry.label, category: categoryLabel, detail: datum.detail }
  }

  function relativePosition(clientX: number, clientY: number) {
    const box = figureRef.current?.getBoundingClientRect()
    return { x: clientX - (box?.left ?? 0) + TOOLTIP_OFFSET_PX, y: clientY - (box?.top ?? 0) + TOOLTIP_OFFSET_PX }
  }

  function onPointerMove(event: PointerEvent, categoryLabel: string, entry: ChartSeries, datum: ChartValue) {
    const { x, y } = relativePosition(event.clientX, event.clientY)
    setTooltip(tooltipFor(categoryLabel, entry, datum, x, y))
  }

  function onFocus(event: FocusEvent<HTMLElement>, categoryLabel: string, entry: ChartSeries, datum: ChartValue) {
    const bar = event.currentTarget.getBoundingClientRect()
    const { x, y } = relativePosition(bar.right, bar.top)
    setTooltip(tooltipFor(categoryLabel, entry, datum, x, y))
  }

  return (
    <figure className="viz-card" ref={figureRef} aria-labelledby={titleId}>
      <figcaption>
        <h4 id={titleId}>{title}</h4>
        <p>{subtitle}</p>
      </figcaption>
      <div className="viz-toolbar">
        {series.length > 1 ? (
          <ul className="viz-legend">
            {series.map((entry) => (
              <li key={entry.key}>
                <span className="viz-swatch" style={{ background: entry.color }} aria-hidden="true" />
                {entry.label}
              </li>
            ))}
          </ul>
        ) : (
          <span />
        )}
        <button type="button" className="viz-table-toggle" onClick={() => setShowTable((shown) => !shown)} aria-pressed={showTable}>
          {showTable ? 'Chart' : 'Table'}
        </button>
      </div>

      {showTable ? (
        <table className="viz-table">
          <thead>
            <tr>
              <th scope="col" />
              {series.map((entry) => (
                <th key={entry.key} scope="col">
                  {entry.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((category) => (
              <tr key={category.key}>
                <th scope="row">{category.label}</th>
                {series.map((entry) => {
                  const datum = valueOf(category.key, entry.key)
                  return (
                    <td key={entry.key}>
                      {datum ? (
                        <>
                          <strong>{format(datum.value)}</strong>
                          <span className="viz-muted"> · {datum.detail}</span>
                        </>
                      ) : (
                        <span className="viz-muted">{emptyLabel}</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="viz-bars" onPointerLeave={() => setTooltip(null)}>
          {categories.map((category) => (
            <div key={category.key} className="viz-bar-group">
              <div className="viz-category">{category.label}</div>
              <div className="viz-tracks">
                {series.map((entry) => {
                  const datum = valueOf(category.key, entry.key)
                  if (!datum) {
                    return (
                      <div key={entry.key} className="viz-track">
                        <span className="viz-empty">
                          {entry.label}: {emptyLabel}
                        </span>
                      </div>
                    )
                  }
                  const share = (datum.value / maxValue) * MAX_BAR_SHARE * 100
                  return (
                    <div key={entry.key} className="viz-track">
                      <span
                        className="viz-bar"
                        style={{ width: `${share}%`, background: entry.color }}
                        tabIndex={0}
                        role="img"
                        aria-label={`${category.label}, ${entry.label}: ${format(datum.value)} (${datum.detail})`}
                        onPointerMove={(event) => onPointerMove(event, category.label, entry, datum)}
                        onFocus={(event) => onFocus(event, category.label, entry, datum)}
                        onBlur={() => setTooltip(null)}
                      />
                      <span className="viz-value">{format(datum.value)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {tooltip && !showTable && (
        <div className="viz-tooltip" style={{ left: tooltip.x, top: tooltip.y }} role="status">
          <strong>{tooltip.value}</strong>
          <span>
            {tooltip.category} · {tooltip.series}
          </span>
          <span className="viz-muted">{tooltip.detail}</span>
        </div>
      )}
    </figure>
  )
}
