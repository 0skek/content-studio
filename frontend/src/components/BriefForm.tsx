import { useState, type FormEvent } from 'react'
import { api, errorText, type Brief, type Language } from '../api'

const LANGUAGE_OPTIONS: { code: Language; label: string }[] = [
  { code: 'bn', label: 'Bengali (বাংলা)' },
  { code: 'en', label: 'English' },
]
const EMPTY_FIELDS = { title: '', goal: '', audience: '', tone: '' }

interface BriefFormProps {
  onCreated: (brief: Brief) => void
}

export function BriefForm({ onCreated }: BriefFormProps) {
  const [fields, setFields] = useState(EMPTY_FIELDS)
  const [languages, setLanguages] = useState<Language[]>(['bn', 'en'])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      const brief = await api.createBrief({ ...fields, languages })
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
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Generate posts'}
      </button>
    </form>
  )
}
