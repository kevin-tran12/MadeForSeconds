import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { useDarkMode } from '../../hooks/useDarkMode'
import { Button } from '../ui/Button'
import { SearchWithSuggestions } from '../search/SearchWithSuggestions'

export function Header() {
  const { isAdmin, logout } = useAuth()
  const { isDark, toggle: toggleDark } = useDarkMode()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `text-sm font-medium transition-colors ${
      isActive ? 'text-primary-600' : 'text-gray-700 dark:text-stone-300 hover:text-primary-600'
    }`

  return (
    <header className="no-print sticky top-0 z-40 border-b border-surface-darker bg-surface/95 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
        {/* Logo */}
        <Link
          to="/"
          className="font-display text-xl font-bold text-primary-600 hover:text-primary-700 shrink-0"
        >
          MadeForSeconds
        </Link>

        {/* Desktop nav + search */}
        <div className="hidden md:flex items-center gap-6">
          {/* Nav links — always visible */}
          <nav className="flex items-center gap-6">
            <NavLink to="/" end className={navLinkClass}>
              Home
            </NavLink>
            <NavLink to="/recipes/" className={navLinkClass}>
              Recipes
            </NavLink>
            <NavLink to="/about/" className={navLinkClass}>
              About
            </NavLink>
            {isAdmin && (
              <NavLink to="/admin/" className={navLinkClass}>
                Admin
              </NavLink>
            )}
          </nav>

          {/* Animated search bar — expands from right without covering tabs */}
          <div
            style={{
              maxWidth: searchOpen ? '22rem' : '0',
              opacity: searchOpen ? 1 : 0,
              pointerEvents: searchOpen ? 'auto' : 'none',
              overflow: searchOpen ? 'visible' : 'hidden',
            }}
            className="transition-[max-width,opacity] duration-300 ease-in-out"
          >
            <div className="w-[22rem] pl-1">
              <SearchWithSuggestions
                autoFocus={searchOpen}
                onClose={() => setSearchOpen(false)}
              />
            </div>
          </div>

          {/* Search / Close toggle button */}
          <button
            onClick={() => setSearchOpen((v) => !v)}
            className={`rounded-lg p-1.5 transition-all duration-200 ${
              searchOpen
                ? 'text-primary-600'
                : 'text-gray-500 dark:text-stone-400 hover:text-primary-600'
            }`}
            aria-label={searchOpen ? 'Close search' : 'Open search'}
          >
            {searchOpen ? (
              <svg
                className="h-5 w-5 transition-transform duration-200 rotate-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            ) : (
              <svg
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"
                />
              </svg>
            )}
          </button>
        </div>

        {/* Dark mode toggle (desktop) */}
        <button
          onClick={toggleDark}
          className="hidden md:flex items-center justify-center rounded-lg p-1.5 text-gray-500 dark:text-stone-400 transition-colors hover:text-primary-600 dark:hover:text-primary-400"
          aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          title={isDark ? 'Light mode' : 'Dark mode'}
        >
          {isDark ? (
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          ) : (
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          )}
        </button>

        {/* Auth area (desktop) */}
        <div className="hidden md:flex items-center gap-2">
          <Link
            to="/support/"
            className="rounded-full bg-amber-500 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-600 transition-colors"
          >
            Donate
          </Link>

          {isAdmin && (
            <Button variant="ghost" size="sm" onClick={logout}>
              Log out
            </Button>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          className="md:hidden p-2 text-gray-600 dark:text-stone-400 hover:text-gray-900 dark:hover:text-stone-100"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label="Toggle menu"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {mobileOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="border-t border-surface-darker bg-surface px-4 py-3 md:hidden">
          {/* Mobile search */}
          <div className="mb-3">
            <SearchWithSuggestions onClose={() => setMobileOpen(false)} />
          </div>

          <nav className="flex flex-col gap-3">
            {/* Dark mode toggle (mobile) */}
            <button
              onClick={toggleDark}
              className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-stone-300 hover:text-primary-600"
            >
              {isDark ? (
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              ) : (
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
              )}
              {isDark ? 'Light mode' : 'Dark mode'}
            </button>
            <NavLink to="/" end className={navLinkClass} onClick={() => setMobileOpen(false)}>
              Home
            </NavLink>
            <NavLink to="/recipes/" className={navLinkClass} onClick={() => setMobileOpen(false)}>
              Recipes
            </NavLink>
            <NavLink to="/about/" className={navLinkClass} onClick={() => setMobileOpen(false)}>
              About
            </NavLink>
            {isAdmin && (
              <NavLink to="/admin/" className={navLinkClass} onClick={() => setMobileOpen(false)}>
                Admin
              </NavLink>
            )}
            <div className="border-t border-surface-darker pt-3 mt-1 flex flex-col gap-2">
              <Link
                to="/support/"
                onClick={() => setMobileOpen(false)}
                className="rounded-lg bg-amber-500 px-3 py-2 text-sm font-semibold text-white text-center hover:bg-amber-600 transition-colors"
              >
                Donate
              </Link>
              {isAdmin && (
                <Button variant="ghost" size="sm" onClick={logout}>
                  Log out
                </Button>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  )
}
