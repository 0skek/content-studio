import { useEffect, useState } from 'react'
import { Flask, Plus, WarningCircle } from '@phosphor-icons/react'
import {
  api,
  errorText,
  type Brief,
  type BriefSummary,
  type Channel,
  type DeletedBrief,
  type TakenDown,
} from './api'
import { AdapterBench } from './components/AdapterBench'
import { LogoMark } from './components/Brand'
import { BriefForm } from './components/BriefForm'
import { BriefList } from './components/BriefList'
import { BriefView } from './components/BriefView'
import { ClockBar } from './components/ClockBar'
import { ConfirmProvider } from './components/ConfirmProvider'
import { FeedsView } from './components/FeedsView'
import { ReportsView } from './components/ReportsView'

type Tab = 'studio' | 'feeds' | 'reports' | 'bench'
const TABS: { id: Tab; label: string }[] = [
  { id: 'studio', label: 'Studio' },
  { id: 'feeds', label: 'Channel feeds' },
  { id: 'reports', label: 'Reports' },
  { id: 'bench', label: 'Adapter bench' },
]

// The open tab lives in the URL hash (#reports), so a tab can be linked or reloaded directly.
function tabFromHash(): Tab {
  const hash = window.location.hash.slice(1)
  return TABS.find((tab) => tab.id === hash)?.id ?? 'studio'
}

function App() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [briefs, setBriefs] = useState<BriefSummary[] | null>(null)
  // null means the New brief composer is open.
  const [selectedBriefId, setSelectedBriefId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
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

  // Back/forward and hand-edited URLs change the hash without a reload; follow them.
  useEffect(() => {
    const followHash = () => setTabState(tabFromHash())
    window.addEventListener('hashchange', followHash)
    return () => window.removeEventListener('hashchange', followHash)
  }, [])

  useEffect(() => {
    api.listChannels().then(setChannels).catch(showLoadError)
    api.listBriefs().then(setBriefs).catch(showLoadError)
  }, [])

  function selectBrief(briefId: number | null) {
    setSelectedBriefId(briefId)
    setNotice(null)
  }

  function handleCreated(brief: Brief) {
    selectBrief(brief.id)
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
    <ConfirmProvider>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#studio" onClick={() => setTab('studio')}>
            <LogoMark />
            <span className="brand-name">Content Studio</span>
          </a>
          <nav className="tabs" aria-label="Sections">
            {TABS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                className={entry.id === 'bench' ? 'tab tab-lab' : 'tab'}
                aria-current={tab === entry.id ? 'page' : undefined}
                title={
                  entry.id === 'bench'
                    ? 'Experiment corner for the hackathon: shows the adapters rejecting constraint violations. Nothing is stored.'
                    : undefined
                }
                onClick={() => setTab(entry.id)}
              >
                {entry.id === 'bench' && <Flask size={15} weight="duotone" aria-hidden="true" />}
                {entry.label}
                {entry.id === 'bench' && <span className="tab-tag">Experiment</span>}
                {entry.id === 'reports' && writingReport && <span className="tab-busy" aria-label="writing a report" />}
              </button>
            ))}
          </nav>
          <div className="topbar-tools">
            <ClockBar onPublished={() => setPublishedToken((token) => token + 1)} />
          </div>
        </div>
      </header>

      {loadError && (
        <div className="banner banner-error" role="alert">
          <WarningCircle size={18} weight="bold" aria-hidden="true" /> {loadError}
        </div>
      )}

      <main id="main" className="main">
        {tab === 'bench' && <AdapterBench channels={channels} />}
        {tab === 'feeds' && <FeedsView channels={channels} refreshToken={publishedToken} onTakenDown={handleTakenDown} />}
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
          <div className="studio">
            <aside className="rail" aria-label="Briefs">
              <div className="rail-head">
                <h2>Briefs</h2>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  aria-pressed={selectedBriefId === null}
                  onClick={() => selectBrief(null)}
                >
                  <Plus size={14} weight="bold" aria-hidden="true" /> New brief
                </button>
              </div>
              <BriefList briefs={briefs} selectedBriefId={selectedBriefId} onSelect={selectBrief} />
            </aside>
            <div className="stage">
              {notice && (
                <p className="notice" role="status">
                  {notice}
                </p>
              )}
              {/* The composer stays mounted, so a half-written brief survives a look at another brief. */}
              <div hidden={selectedBriefId !== null}>
                <BriefForm onCreated={handleCreated} insightsVersion={insightsVersion} />
              </div>
              {selectedBriefId !== null && (
                <BriefView
                  key={selectedBriefId}
                  briefId={selectedBriefId}
                  channels={channels}
                  refreshToken={publishedToken}
                  onDeleted={handleBriefDeleted}
                  onTakenDown={handleTakenDown}
                />
              )}
            </div>
          </div>
        )}
      </main>
    </ConfirmProvider>
  )
}

export default App
