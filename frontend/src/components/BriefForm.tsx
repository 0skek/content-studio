import { useEffect, useState, type FormEvent } from 'react'
import { api, errorText, type Brief, type Insight, type Language } from '../api'

const LANGUAGE_OPTIONS: { code: Language; label: string }[] = [
  { code: 'bn', label: 'Bengali (বাংলা)' },
  { code: 'en', label: 'English' },
]
const EMPTY_FIELDS = { title: '', goal: '', audience: '', tone: '' }

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
  const [insights, setInsights] = useState<Insight[]>([])
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
      const insightIds = insights.map((insight) => insight.id).filter((id) => !skippedInsightIds.includes(id))
      const brief = await api.createBrief({ ...fields, languages, insight_ids: insightIds })
      setFields(EMPTY_FIELDS)
      onCreated(brief)
    } catch (caught) {
      setError(errorText(caught))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="panel brief-form" onSubmit={handleSubmit}>
      <h2>New brief</h2>
      <label>
        Title
        <input
          required
          value={fields.title}
          onChange={(event) => updateField('title', event.target.value)}
          placeholder="Pohela Boishakh collection"
        />
      </label>
      <label>
        Goal
        <textarea
          required
          rows={3}
          value={fields.goal}
          onChange={(event) => updateField('goal', event.target.value)}
          placeholder="Bring young professionals into the store for the new-year collection"
        />
      </label>
      <label>
        Audience
        <input
          required
          value={fields.audience}
          onChange={(event) => updateField('audience', event.target.value)}
          placeholder="Young professionals in Dhaka"
        />
      </label>
      <label>
        Tone
        <input
          required
          value={fields.tone}
          onChange={(event) => updateField('tone', event.target.value)}
          placeholder="Warm, festive"
        />
      </label>
      <fieldset>
        <legend>Languages</legend>
        {LANGUAGE_OPTIONS.map((option) => (
          <label key={option.code} className="checkbox">
            <input
              type="checkbox"
              checked={languages.includes(option.code)}
              onChange={() => toggleLanguage(option.code)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      <fieldset className="insights-fieldset">
        <legend>Insights from the latest report</legend>
        {insights.length === 0 ? (
          <p className="muted">None yet. Generate a weekly report and its insights will appear here.</p>
        ) : (
          <>
            <p className="muted small">Ticked insights are added to the generation prompts (report #{insights[0].report_id}).</p>
            {insights.map((insight) => (
              <label key={insight.id} className="checkbox insight-option">
                <input
                  type="checkbox"
                  checked={!skippedInsightIds.includes(insight.id)}
                  onChange={() => toggleInsight(insight.id)}
                />
                {insight.text}
              </label>
            ))}
          </>
        )}
      </fieldset>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Generate posts'}
      </button>
    </form>
  )
}
