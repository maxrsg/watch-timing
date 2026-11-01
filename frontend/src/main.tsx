import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

declare global {
  interface Window {
    __showStartupError?: (error: unknown) => void
  }
}

// Dev only: remove service workers left over from earlier dev sessions (the dev server no longer
// registers one; an old one can keep serving stale files).
if (import.meta.env.DEV && 'serviceWorker' in navigator) {
  void navigator.serviceWorker
    .getRegistrations()
    .then((registrations) => registrations.forEach((r) => void r.unregister()))
}

// The app is dark only; the class turns on the components' `dark:` styles.
document.documentElement.classList.add('dark')

createRoot(document.getElementById('root')!, {
  // A render error would otherwise unmount everything and leave a blank page.
  // Deferred: React empties the root after reporting the error.
  onUncaughtError: (error) => setTimeout(() => window.__showStartupError?.(error)),
}).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
