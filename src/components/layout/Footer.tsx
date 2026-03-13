export function Footer() {
  return (
    <footer className="mt-auto border-t border-surface-darker bg-surface-dark py-6">
      <div className="mx-auto max-w-6xl px-4 text-center text-sm text-gray-500">
        &copy; {new Date().getFullYear()} MadeForSeconds
      </div>
    </footer>
  )
}
