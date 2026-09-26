import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted fonts, so the demo never depends on a font CDN: Archivo for the interface, Hind Siliguri for
// Bengali (Archivo has no Bengali glyphs, so the browser falls through to it), IBM Plex Mono for IDs and numbers.
import '@fontsource-variable/archivo/standard.css'
import '@fontsource/hind-siliguri/bengali-400.css'
import '@fontsource/hind-siliguri/bengali-500.css'
import '@fontsource/hind-siliguri/bengali-600.css'
import '@fontsource/hind-siliguri/bengali-700.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
