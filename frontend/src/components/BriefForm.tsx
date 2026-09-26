import { useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, Check, Lightbulb } from '@phosphor-icons/react'
import { api, errorText, type Brief, type Insight, type Language } from '../api'
import { splitLead } from '../format'

const LANGUAGE_OPTIONS: { code: Language; label: string; native: string }[] = [
  { code: 'bn', label: 'Bengali', native: 'বাংলা' },
  { code: 'en', label: 'English', native: 'English' },
]
const EMPTY_FIELDS = { title: '', goal: '', audience: '', tone: '' }
// One call plans every channel's photo; each language then gets one copy call.
const SCENE_CALLS = 1

interface BriefFormProps {
  onCreated: (brief: Brief) => void
  // Changes when a new weekly report (and so new insights) exists.
  insightsVersion: number
}

export function BriefForm({ onCreated, insightsVersion }: BriefFormProps) {
  const [fields, setFields] = useState(EMPTY_FIELDS)
  const [languages, setLanguages] = useState<Language[]>(['bn', 'en'])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [insights, setInsights] = useState<Insight[] | null>(null)
  // Insights the user unticked; everything else offered is applied.
  const [skippedInsightIds, setSkippedInsightIds] = useState<number[]>([])

  useEffect(() => {
    let cancelled = false
    api
      .latestInsights()
      .then((latest) => {
        if (cancelled) return
        setInsights(latest)
        setSkippedInsightIds([])
      })
      .catch((caught) => !cancelled && setError(errorText(caught)))
    return () => {
      cancelled = true
    }
  }, [insightsVersion])

  function toggleInsight(insightId: number) {
    setSkippedInsightIds((current) =>
      current.includes(insightId) ? current.filter((id) => id !== insightId) : [...current, insightId],
    )
  }

  function updateField(name: keyof typeof EMPTY_FIELDS, value: string) {
    setFields((current) => ({ ...current, [name]: value }))
  }

  function toggleLanguage(code: Language) {
    setLanguages((current) =>
      current.includes(code) ? current.filter((language) => language !== code) : [...current, code],
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (languages.length === 0) {
      setError('Pick at least one language.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const insightIds = (insights ?? []).map((insight) => insight.id).filter((id) => !skippedInsightIds.includes(id))
      const brief = await api.createBrief({ ...fields, languages, insight_ids: insightIds })
      setFields(EMPTY_FIELDS)
      onCreated(brief)
    } catch (caught) {
      setError(errorText(caught))
    } finally {
      setSubmitting(false)
    }
  }

  const appliedCount = (insights ?? []).filter((insight) => !skippedInsightIds.includes(insight.id)).length

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <header className="page-head">
        <p className="eyebrow">Studio</p>
        <h1>New brief</h1>
        <p className="lede">
          Each channel gets its own photo at its native size, and its own copy written separately in each language.
          Nothing is published until you approve it.
        </p>
      </header>

      <div className="composer-grid">
        <div className="composer-fields">
          <label className="field">
            <span className="field-label">Title</span>
            <input
              required
              value={fields.title}
              onChange={(event) => updateField('title', event.target.value)}
              placeholder="Durga Puja handloom collection"
            />
          </label>
          <label className="field">
            <span className="field-label">Goal</span>
            <textarea
              required
              rows={3}
              value={fields.goal}
              onChange={(event) => updateField('goal', event.target.value)}
              placeholder="Bring young professionals into our Gariahat store for the new Pujo collection, 15% off until Shashthi"
            />
            <span className="field-hint">State the facts you want used: offers, dates, places. The copy won't invent any.</span>
          </label>
          <div className="field-row">
            <label className="field">
              <span className="field-label">Audience</span>
              <input
                required
                value={fields.audience}
                onChange={(event) => updateField('audience', event.target.value)}
                placeholder="Young professionals in Kolkata, 22–35"
              />
            </label>
            <label className="field">
              <span className="field-label">Tone</span>
              <input
                required
                value={fields.tone}
                onChange={(event) => updateField('tone', event.target.value)}
                placeholder="Warm, festive, proud of local craft"
              />
            </label>
          </div>
          <fieldset className="field">
            <legend className="field-label">Languages</legend>
            <div className="toggle-row">
              {LANGUAGE_OPTIONS.map((option) => (
                <label key={option.code} className="toggle-chip">
                  <input
                    type="checkbox"
                    checked={languages.includes(option.code)}
                    onChange={() => toggleLanguage(option.code)}
                  />
                  <span className="toggle-check" aria-hidden="true">
                    <Check size={12} weight="bold" />
                  </span>
                  <span lang={option.code}>{option.native}</span>
                  {option.code !== 'en' && <span className="toggle-sub">{option.label}</span>}
                </label>
              ))}
            </div>
            <span className="field-hint">Each language is written on its own, never translated from the other.</span>
          </fieldset>
        </div>

        <fieldset className="composer-insights">
          <legend className="insights-legend">
            <Lightbulb size={16} weight="duotone" aria-hidden="true" />
            Insights from the latest report
            {insights && insights.length > 0 && <span className="mono muted">report #{insights[0].report_id}</span>}
          </legend>
          {insights === null ? (
            <div className="insight-skeletons" aria-hidden="true">
              <div className="skeleton" />
              <div className="skeleton" />
            </div>
          ) : insights.length === 0 ? (
            <p className="insights-empty">
              No report yet. Publish some posts, write a weekly report in Reports, and its insights show up here to
              steer the next brief.
            </p>
          ) : (
            <>
              <p className="insights-note">
                {appliedCount} of {insights.length} ticked. Ticked insights go into the scene and copy prompts.
              </p>
              <ul className="insight-options">
                {insights.map((insight) => {
                  const [lead, rest] = splitLead(insight.text)
                  return (
                    <li key={insight.id}>
                      <label className="insight-option">
                        <input
                          type="checkbox"
                          checked={!skippedInsightIds.includes(insight.id)}
                          onChange={() => toggleInsight(insight.id)}
                        />
                        <span className="toggle-check" aria-hidden="true">
                          <Check size={12} weight="bold" />
                        </span>
                        <span>
                          <strong>{lead}</strong> {rest}
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </fieldset>
      </div>

      <footer className="composer-foot">
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <p className="composer-cost">
          One image per channel · {SCENE_CALLS + languages.length} text-model calls (scenes, then copy per language)
        </p>
        <button type="submit" className="btn btn-primary btn-lg" disabled={submitting}>
          {submitting ? (
            <>
              <span className="spinner" aria-hidden="true" /> Creating…
            </>
          ) : (
            <>
              Generate posts <ArrowRight size={16} weight="bold" aria-hidden="true" />
            </>
          )}
        </button>
      </footer>
    </form>
  )
}
