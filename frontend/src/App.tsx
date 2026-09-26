import { useEffect, useState } from 'react'
import { api, errorText, type Brief, type BriefSummary, type Channel } from './api'
import { BriefForm } from './components/BriefForm'
import { BriefList } from './components/BriefList'
import { BriefView } from './components/BriefView'

function App() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [briefs, setBriefs] = useState<BriefSummary[]>([])
  const [selectedBriefId, setSelectedBriefId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function showLoadError(caught: unknown) {
    setLoadError(errorText(caught))
  }

  useEffect(() => {
    api.listChannels().then(setChannels).catch(showLoadError)
    api.listBriefs().then(setBriefs).catch(showLoadError)
  }, [])

  function handleCreated(brief: Brief) {
    setSelectedBriefId(brief.id)
    api.listBriefs().then(setBriefs).catch(showLoadError)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>AI Content Studio</h1>
        {loadError && <p className="error">{loadError}</p>}
      </header>
      <div className="layout">
        <aside>
          <BriefForm onCreated={handleCreated} />
          <BriefList briefs={briefs} selectedBriefId={selectedBriefId} onSelect={setSelectedBriefId} />
        </aside>
        <main>
          {selectedBriefId === null ? (
            <p className="muted empty-state">Create a brief or pick one from the list.</p>
          ) : (
            <BriefView key={selectedBriefId} briefId={selectedBriefId} channels={channels} />
          )}
        </main>
      </div>
    </div>
  )
}

export default App
