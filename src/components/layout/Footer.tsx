export function Footer() {
  return (
    <footer className="mt-auto border-t border-surface-darker bg-surface-dark py-10">
      <div className="mx-auto max-w-6xl px-4">
        <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
          {/* Social / Linktree */}
          <div className="flex items-center gap-4">
            <a
              href="https://linktr.ee/madeforseconds"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 hover:shadow"
            >
              <svg className="h-4 w-4 text-primary-600" fill="currentColor" viewBox="0 0 24 24">
                <path d="M13.511 5.833L17.5 1.2h-3.132l-2.47 2.871L9.421 1.2H6.289l3.989 4.633L6.289 10.43h3.132l2.477-2.871 2.477 2.871h3.132l-3.998-4.597zM12 10.43V22.8h3V10.43h-3z" />
              </svg>
              Socials
            </a>
          </div>

          {/* Copyright */}
          <div className="text-center text-sm text-gray-500 md:text-right">
            <p>&copy; {new Date().getFullYear()} MadeForSeconds</p>
            <p className="mt-1 text-xs text-gray-400">Recipes worth making again.</p>
          </div>
        </div>
      </div>
    </footer>
  )
}
