import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ConfirmContext, type ConfirmOptions } from '../confirm'

interface PendingConfirm {
  options: ConfirmOptions
  resolve: (confirmed: boolean) => void
}

// A styled replacement for window.confirm: one modal at a time, focus starts on Cancel so Enter never destroys.
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null)

  const confirm = useCallback(
    (options: ConfirmOptions) => new Promise<boolean>((resolve) => setPending({ options, resolve })),
    [],
  )

  function settle(confirmed: boolean) {
    pending?.resolve(confirmed)
    setPending(null)
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && <ConfirmDialog options={pending.options} onSettle={settle} />}
    </ConfirmContext.Provider>
  )
}

function ConfirmDialog({ options, onSettle }: { options: ConfirmOptions; onSettle: (confirmed: boolean) => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    // Guarded because React's dev StrictMode runs effects twice.
    if (dialog && !dialog.open) dialog.showModal()
    cancelRef.current?.focus()
  }, [])

  return (
    <dialog
      ref={dialogRef}
      className="confirm-dialog"
      aria-labelledby="confirm-title"
      onClose={() => onSettle(false)}
      onClick={(event) => event.target === dialogRef.current && onSettle(false)}
    >
      <div className="confirm-body">
        <h2 id="confirm-title">{options.title}</h2>
        <div className="confirm-text">{options.body}</div>
      </div>
      <div className="confirm-actions">
        <button ref={cancelRef} type="button" className="btn btn-ghost" onClick={() => onSettle(false)}>
          Cancel
        </button>
        <button
          type="button"
          className={options.tone === 'danger' ? 'btn btn-danger' : 'btn btn-primary'}
          onClick={() => onSettle(true)}
        >
          {options.confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
