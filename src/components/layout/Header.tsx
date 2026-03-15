import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { Button } from '../ui/Button'
import { SearchWithSuggestions } from '../search/SearchWithSuggestions'

export function Header() {
  const { isAdmin, logout } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `text-sm font-medium transition-colors ${
      isActive ? 'text-primary-600' : 'text-gray-700 hover:text-primary-600'
    }`

  return (
    <header className="sticky top-0 z-40 border-b border-surface-darker bg-surface/95 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
        {/* Logo */}
        <Link
          to="/"
          className="font-display text-xl font-bold text-primary-600 hover:text-primary-700 shrink-0"
        >
          MadeForSeconds
        </Link>

        {/* Desktop nav */}
        <nav className="hidden items-center gap-6 md:flex">
          {searchOpen ? (
            <div className="w-80">
              <SearchWithSuggestions onClose={() => setSearchOpen(false)} />
            </div>
          ) : (
            <>
              <NavLink to="/" end className={navLinkClass}>
                Home
              </NavLink>
              <NavLink to="/recipes" className={navLinkClass}>
                Recipes
              </NavLink>
              <NavLink to="/about" className={navLinkClass}>
                About
              </NavLink>
              {isAdmin && (
                <NavLink to="/admin" className={navLinkClass}>
                  Admin
                </NavLink>
              )}
              <button
                onClick={() => setSearchOpen(true)}
                className="rounded-lg p-1.5 text-gray-500 hover:text-primary-600 transition-colors"
                aria-label="Search"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
                </svg>
              </button>
            </>
          )}
        </nav>

        {/* Auth button (desktop) */}
        <div className="hidden md:block">
          {isAdmin && (
            <Button variant="ghost" size="sm" onClick={logout}>
              Log out
            </Button>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          className="md:hidden p-2 text-gray-600 hover:text-gray-900"
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
            <NavLink to="/" end className={navLinkClass} onClick={() => setMobileOpen(false)}>
              Home
            </NavLink>
            <NavLink to="/recipes" className={navLinkClass} onClick={() => setMobileOpen(false)}>
              Recipes
            </NavLink>
            <NavLink to="/about" className={navLinkClass} onClick={() => setMobileOpen(false)}>
              About
            </NavLink>
            {isAdmin && (
              <NavLink to="/admin" className={navLinkClass} onClick={() => setMobileOpen(false)}>
                Admin
              </NavLink>
            )}
            {isAdmin && (
              <div className="pt-2">
                <Button variant="ghost" size="sm" onClick={logout}>
                  Log out
                </Button>
              </div>
            )}
          </nav>
        </div>
      )}
    </header>
  )
}
