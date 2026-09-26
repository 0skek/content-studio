import { useEffect, useState } from 'react'
import {
  api,
  errorText,
  type Brief,
  type BriefSummary,
  type Channel,
  type DeletedBrief,
  type Health,
  type TakenDown,
} from './api'
import { AdapterBench } from './components/AdapterBench'
import { BriefForm } from './components/BriefForm'
import { BriefList } from './components/BriefList'
import { BriefView } from './components/BriefView'
import { ClockBar } from './components/ClockBar'
import { FeedsView } from './components/FeedsView'
import { ReportsView } from './components/ReportsView'

type Tab = 'studio' | 'feeds' | 'reports' | 'bench'
const TABS: Tab[] = ['studio', 'feeds', 'reports', 'bench']

// The open tab lives in the URL hash (#reports), so a tab can be linked or reloaded directly.
function tabFromHash(): Tab {
  const hash = window.location.hash.slice(1)
  return TABS.find((tab) => tab === hash) ?? 'studio'
}

function App() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [briefs, setBriefs] = useState<BriefSummary[]>([])
  const [selectedBriefId, setSelectedBriefId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [tab, setTabState] = useState<Tab>(tabFromHash)

  function setTab(next: Tab) {
    setTabState(next)
    window.history.replaceState(null, '', `#${next}`)
  }
  // Bumped after the clock bar publishes, so the open brief shows the new statuses.
  const [publishedToken, setPublishedToken] = useState(0)
  // Bumped after a weekly report is written, so the brief form offers its insights.
  const [insightsVersion, setInsightsVersion] = useState(0)
  const [writingReport, setWritingReport] = useState(false)
  // Bumped when deleting a brief also deleted reports, so the Reports tab reloads.
  const [reportsVersion, setReportsVersion] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)

  function showLoadError(caught: unknown) {
    setLoadError(errorText(caught))
  }

  useEffect(() => {
    api.health().then(setHealth).catch(showLoadError)
    api.listChannels().then(setChannels).catch(showLoadError)
    api.listBriefs().then(setBriefs).catch(showLoadError)
  }, [])

  function handleCreated(brief: Brief) {
    setSelectedBriefId(brief.id)
    setNotice(null)
    api.listBriefs().then(setBriefs).catch(showLoadError)
  }

  function handleTakenDown(result: TakenDown) {
    if (result.deleted_report_ids.length > 0) {
      setReportsVersion((version) => version + 1)
      setInsightsVersion((version) => version + 1)
    }
    setPublishedToken((token) => token + 1)
  }

  function handleBriefDeleted(deleted: DeletedBrief) {
    setSelectedBriefId(null)
    api.listBriefs().then(setBriefs).catch(showLoadError)
    const reports = deleted.report_ids.map((id) => `#${id}`).join(', ')
    setNotice(
      `Deleted brief #${deleted.brief_id} and its ${deleted.post_ids.length} posts.` +
        (deleted.report_ids.length > 0 ? ` Reports ${reports} cited those posts, so they were deleted too.` : ''),
    )
    if (deleted.report_ids.length > 0) {
      setReportsVersion((version) => version + 1)
      setInsightsVersion((version) => version + 1)
    }
    setPublishedToken((token) => token + 1) // the feeds drop the deleted posts
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>AI Content Studio</h1>
        {health && !health.production_providers && (
          <span className="dev-chip" title="Local development providers are on; switch them off in .env before the demo.">
            DEV: text={health.text_provider} · images={health.image_provider}
          </span>
        )}
        <nav className="tabs">
          <button type="button" className={tab === 'studio' ? 'active' : ''} onClick={() => setTab('studio')}>
            Studio
          </button>
          <button type="button" className={tab === 'feeds' ? 'active' : ''} onClick={() => setTab('feeds')}>
            Channel feeds
          </button>
          <button type="button" className={tab === 'reports' ? 'active' : ''} onClick={() => setTab('reports')}>
            Reports
            {writingReport && (
              <span className="tab-busy">
                <span className="button-spinner" aria-hidden="true" /> writing…
              </span>
            )}
          </button>
          <button type="button" className={tab === 'bench' ? 'active' : ''} onClick={() => setTab('bench')}>
            Adapter test bench
          </button>
        </nav>
        <ClockBar onPublished={() => setPublishedToken((token) => token + 1)} />
        {loadError && <p className="error">{loadError}</p>}
      </header>
      {tab === 'bench' && <AdapterBench channels={channels} />}
      {tab === 'feeds' && (
        <FeedsView
          channels={channels}
          refreshToken={publishedToken}
          onTakenDown={handleTakenDown}
        />
      )}
      {/* Kept mounted while hidden, so a report being written survives switching tabs. */}
      <div hidden={tab !== 'reports'}>
        <ReportsView
          channels={channels}
          reportsVersion={reportsVersion}
          visible={tab === 'reports'}
          onReportsChanged={() => setInsightsVersion((version) => version + 1)}
          onGeneratingChange={setWritingReport}
        />
      </div>
      {tab === 'studio' && (
      <div className="layout">
        <aside>
          <BriefForm onCreated={handleCreated} insightsVersion={insightsVersion} />
          <BriefList
            briefs={briefs}
            selectedBriefId={selectedBriefId}
            onSelect={(briefId) => {
              setSelectedBriefId(briefId)
              setNotice(null)
            }}
          />
        </aside>
        <main>
          {notice && (
            <p className="notice" role="status">
              {notice}
            </p>
          )}
          {selectedBriefId === null ? (
            <p className="muted empty-state">Create a brief or pick one from the list.</p>
          ) : (
            <BriefView
              key={selectedBriefId}
              briefId={selectedBriefId}
              channels={channels}
              refreshToken={publishedToken}
              onDeleted={handleBriefDeleted}
              onTakenDown={handleTakenDown}
            />
          )}
        </main>
      </div>
      )}
    </div>
  )
}

export default App
