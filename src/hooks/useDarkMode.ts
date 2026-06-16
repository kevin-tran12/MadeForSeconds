import { useSyncExternalStore } from 'react'

// Single source of truth is the `.dark` class on <html> (set by the init script
// in index.html). useSyncExternalStore keeps every hook instance — and every
// open tab — consistent with it.
const THEME_EVENT = 'themechange'

function subscribe(callback: () => void) {
  // Same-document, cross-instance updates
  window.addEventListener(THEME_EVENT, callback)
  // Cross-tab updates: reconcile this tab's DOM with the other tab's choice
  function onStorage(e: StorageEvent) {
    if (e.key !== 'theme') return
    document.documentElement.classList.toggle('dark', e.newValue === 'dark')
    callback()
  }
  window.addEventListener('storage', onStorage)
  return () => {
    window.removeEventListener(THEME_EVENT, callback)
    window.removeEventListener('storage', onStorage)
  }
}

function getSnapshot() {
  return document.documentElement.classList.contains('dark')
}

export function useDarkMode() {
  const isDark = useSyncExternalStore(subscribe, getSnapshot, () => false)

  function toggle() {
    const next = !document.documentElement.classList.contains('dark')
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('theme', next ? 'dark' : 'light')
    window.dispatchEvent(new Event(THEME_EVENT))
  }

  return { isDark, toggle }
}
