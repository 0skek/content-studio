import type { BriefSummary } from '../api'
import { formatShortDate } from '../format'

const SKELETON_ROWS = 3

interface BriefListProps {
  // null while the list is loading.
  briefs: BriefSummary[] | null
  selectedBriefId: number | null
  onSelect: (briefId: number) => void
}

export function BriefList({ briefs, selectedBriefId, onSelect }: BriefListProps) {
  if (briefs === null) {
    return (
      <ul className="rail-list" aria-hidden="true">
        {Array.from({ length: SKELETON_ROWS }, (_, index) => (
          <li key={index} className="rail-skeleton skeleton" />
        ))}
      </ul>
    )
  }
  if (briefs.length === 0) {
    return <p className="rail-empty">No briefs yet. Write the first one on the right.</p>
  }
  return (
    <ul className="rail-list">
      {briefs.map((brief) => (
        <li key={brief.id}>
          <button
            type="button"
            className="rail-item"
            aria-current={brief.id === selectedBriefId ? 'true' : undefined}
            onClick={() => onSelect(brief.id)}
          >
            <span className="rail-item-title">{brief.title}</span>
            <span className="rail-item-meta">
              <span className="mono">#{brief.id}</span>
              <span>{formatShortDate(brief.created_at)}</span>
              <span className="rail-langs">
                {brief.languages.map((language) => (
                  <span key={language} className="lang-tag">
                    {language.toUpperCase()}
                  </span>
                ))}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
