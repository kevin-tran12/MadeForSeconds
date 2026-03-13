import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="text-6xl">🍽️</div>
      <h1 className="font-display text-3xl font-bold text-gray-900">Page not found</h1>
      <p className="text-gray-500">That page doesn't exist — maybe the recipe moved?</p>
      <Link
        to="/"
        className="mt-2 rounded-lg bg-primary-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-primary-700"
      >
        Back to home
      </Link>
    </div>
  )
}
