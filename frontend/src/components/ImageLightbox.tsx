import { useEffect, useRef, useState, type MouseEvent } from 'react'

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
        <span>{title}</span>
        <button type="button" onClick={() => setActualSize(!actualSize)}>
          {toggleLabel}
        </button>
        <a href={src} target="_blank" rel="noreferrer">
          Open in new tab
        </a>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
    </dialog>
  )
}
