import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { ArrowSquareOut, X } from '@phosphor-icons/react'

interface ImageLightboxProps {
  src: string
  alt: string
  title: string
  onClose: () => void
}

// Full-screen view of one image. Esc, the Close button or a click on the dark area closes it;
// clicking the image switches between "fit to screen" and actual pixels.
export function ImageLightbox({ src, alt, title, onClose }: ImageLightboxProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const [actualSize, setActualSize] = useState(false)

  useEffect(() => {
    const dialog = dialogRef.current
    // Guarded because React's dev StrictMode runs effects twice.
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  function closeOnBackgroundClick(event: MouseEvent<HTMLDialogElement>) {
    if (event.target === dialogRef.current || event.target === stageRef.current) onClose()
  }

  const toggleLabel = actualSize ? 'Fit to screen' : 'Actual size'

  return (
    <dialog
      ref={dialogRef}
      className={actualSize ? 'lightbox actual-size' : 'lightbox'}
      aria-label={title}
      onClose={onClose}
      onClick={closeOnBackgroundClick}
    >
      <div ref={stageRef} className="lightbox-stage">
        <img src={src} alt={alt} title={`Click for ${toggleLabel.toLowerCase()}`} onClick={() => setActualSize(!actualSize)} />
      </div>
      <div className="lightbox-bar">
        <span className="lightbox-title mono">{title}</span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setActualSize(!actualSize)}>
          {toggleLabel}
        </button>
        <a className="btn btn-ghost btn-sm" href={src} target="_blank" rel="noreferrer">
          <ArrowSquareOut size={14} aria-hidden="true" /> Open in new tab
        </a>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
          <X size={14} aria-hidden="true" /> Close
        </button>
      </div>
    </dialog>
  )
}
