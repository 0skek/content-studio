import type { BriefSummary } from '../api'

interface BriefListProps {
  briefs: BriefSummary[]
  selectedBriefId: number | null
  onSelect: (briefId: number) => void
}

export function BriefList({ briefs, selectedBriefId, onSelect }: BriefListProps) {
  return (
    <nav className="panel brief-list">
      <h2>Briefs</h2>
      {briefs.length === 0 && <p className="muted">No briefs yet.</p>}
      <ul>
        {briefs.map((brief) => (
          <li key={brief.id}>
            <button
              type="button"
              className={brief.id === selectedBriefId ? 'selected' : undefined}
              onClick={() => onSelect(brief.id)}
            >
              <span className="brief-title">
                #{brief.id} {brief.title}
              </span>
              <span className="muted">{new Date(brief.created_at).toLocaleString()}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
