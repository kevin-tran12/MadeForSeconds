import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminAssistantApi, type AssistantFeedbackRow } from '../../lib/api'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { EmptyState } from '../ui/EmptyState'

/**
 * Reader feedback on Sous Chef answers, thumbs-down first. The point is to
 * turn a wrong answer into that recipe's "Sous Chef notes" — hence the link
 * straight to the recipe.
 */
export function SousChefFeedbackPanel() {
  const [rows, setRows] = useState<AssistantFeedbackRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    adminAssistantApi
      .listFeedback(50)
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load feedback'))
  }, [])

  if (error) {
    return <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
  }
  if (rows === null) return <LoadingSpinner className="py-12" />
  if (rows.length === 0) {
    return <EmptyState title="No feedback yet" message="Thumbs from readers on Sous Chef answers will show up here, worst first." />
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-surface-darker bg-white">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-2">Rating</th>
            <th className="px-4 py-2">Recipe</th>
            <th className="px-4 py-2">Question</th>
            <th className="px-4 py-2">When</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <>
              <tr
                key={row.id}
                className="cursor-pointer border-t border-gray-100 hover:bg-gray-50"
                onClick={() => setOpen(open === row.id ? null : row.id)}
              >
                <td className="px-4 py-2">
                  <span className={row.rating === 'down' ? 'text-red-600' : 'text-green-600'}>
                    {row.rating === 'down' ? '👎 Not helpful' : '👍 Helpful'}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <Link to={`/recipes/${row.slug}/`} className="text-primary-600 hover:underline" onClick={(e) => e.stopPropagation()}>
                    {row.slug}
                  </Link>
                </td>
                <td className="max-w-md truncate px-4 py-2 text-gray-700">{row.question}</td>
                <td className="whitespace-nowrap px-4 py-2 text-gray-500">
                  {row.created_at ? new Date(row.created_at).toLocaleDateString() : ''}
                </td>
              </tr>
              {open === row.id && (
                <tr key={`${row.id}-detail`} className="border-t border-gray-100 bg-gray-50">
                  <td colSpan={4} className="px-4 py-3 text-sm text-gray-700">
                    <p className="font-semibold text-gray-900">Answer</p>
                    <p className="whitespace-pre-wrap">{row.answer}</p>
                    {row.comment && (
                      <>
                        <p className="mt-2 font-semibold text-gray-900">Reader comment</p>
                        <p>{row.comment}</p>
                      </>
                    )}
                    <p className="mt-2 text-xs text-gray-500">Model: {row.model}</p>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  )
}
