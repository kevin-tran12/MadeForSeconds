import { useRef, useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { Button } from '../ui/Button'

export function Header() {
  const { isAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchValue, setSearchValue] = useState('')
  const searchInputRef = useRef<HTMLInputElement>(null)

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `text-sm font-medium transition-colors ${
      isActive ? 'text-primary-600' : 'text-gray-700 hover:text-primary-600'
    }`

  function openSearch() {
    setSearchOpen(true)
    setTimeout(() => searchInputRef.current?.focus(), 50)
  }

  function closeSearch() {
    setSearchOpen(false)
    setSearchValue('')
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    const q = searchValue.trim()
    closeSearch()
    if (q) navigate(`/recipes?q=${encodeURIComponent(q)}`)
    else navigate('/recipes')
  }

  function handleSearchKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') closeSearch()
  }

  function handleMobileSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    const q = searchValue.trim()
    setMobileOpen(false)
    setSearchValue('')
    if (q) navigate(`/recipes?q=${encodeURIComponent(q)}`)
    else navigate('/recipes')
  }

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
            <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-1.5 shadow-sm ring-2 ring-primary-100 focus-within:ring-primary-300">
                <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
                </svg>
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchValue}
                  onChange={(e) => setSearchValue(e.target.value)}
                  onKeyDown={handleSearchKeyDown}
                  placeholder="Search recipes…"
                  className="w-48 bg-transparent text-sm text-gray-900 placeholder-gray-400 outline-none"
                />
              </div>
              <button
                type="submit"
                className="rounded-lg bg-primary-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-400 active:scale-95 transition-all"
              >
                Go
              </button>
              <button
                type="button"
                onClick={closeSearch}
                className="rounded-lg p-1.5 text-gray-400 hover:text-gray-600"
                aria-label="Close search"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </form>
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
                onClick={openSearch}
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
          <form onSubmit={handleMobileSearchSubmit} className="mb-3 flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2">
            <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
            </svg>
            <input
              type="text"
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              placeholder="Search recipes…"
              className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 outline-none"
            />
          </form>

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
