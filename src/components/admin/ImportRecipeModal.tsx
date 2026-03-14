import { useRef, useState } from 'react'
import type { RecipeFormData } from '../../lib/types'
import { adminApi } from '../../lib/api'
import { Button } from '../ui/Button'

interface ImportRecipeModalProps {
  onSuccess: (data: RecipeFormData) => void
  onClose: () => void
}

export function ImportRecipeModal({ onSuccess, onClose }: ImportRecipeModalProps) {
  const [tab, setTab] = useState<'pdf' | 'text'>('pdf')
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleParse() {
    if (tab === 'pdf' && !file) return
    if (tab === 'text' && !text.trim()) return

    setError(null)
    setParsing(true)
    try {
      const data = await adminApi.parseRecipe(
        tab === 'pdf' ? { file: file! } : { text: text.trim() }
      )
      onSuccess(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to parse recipe')
    } finally {
      setParsing(false)
    }
  }

  const canParse = tab === 'pdf' ? !!file : !!text.trim()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-lg rounded-3xl bg-white shadow-2xl">
        <div className="p-6">
          <div className="mb-5 flex items-center justify-between">
            <div>
              <h2 className="font-display text-xl font-bold text-gray-900">Import Recipe</h2>
              <p className="mt-0.5 text-sm text-gray-500">
                Paste a recipe or upload a PDF — Claude will fill in the form.
              </p>
            </div>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Tabs */}
          <div className="mb-4 flex rounded-xl bg-gray-100 p-1">
            {(['pdf', 'text'] as const).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError(null) }}
                className={`flex-1 rounded-lg py-1.5 text-sm font-medium transition-all ${
                  tab === t
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'pdf' ? 'Upload PDF' : 'Paste Text'}
              </button>
            ))}
          </div>

          {/* Input area */}
          {tab === 'pdf' ? (
            <div
              onClick={() => fileInputRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-8 transition-colors ${
                file
                  ? 'border-primary-300 bg-primary-50'
                  : 'border-gray-200 bg-gray-50 hover:border-primary-300 hover:bg-primary-50/40'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null) }}
              />
              {file ? (
                <>
                  <svg className="h-8 w-8 text-primary-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <p className="text-sm font-medium text-primary-700">{file.name}</p>
                  <p className="text-xs text-gray-400">Click to change</p>
                </>
              ) : (
                <>
                  <svg className="h-8 w-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  <p className="text-sm font-medium text-gray-700">Click to upload a PDF</p>
                  <p className="text-xs text-gray-400">Recipe book pages, printouts, etc.</p>
                </>
              )}
            </div>
          ) : (
            <textarea
              value={text}
              onChange={(e) => { setText(e.target.value); setError(null) }}
              placeholder="Paste recipe text here — from a website, notes app, anywhere..."
              rows={8}
              disabled={parsing}
              className="w-full resize-none rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-relaxed text-gray-800 placeholder:text-gray-400 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-100 disabled:opacity-50"
            />
          )}

          {error && (
            <p className="mt-3 rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-600">{error}</p>
          )}

          <div className="mt-4 flex gap-3">
            <Button variant="ghost" onClick={onClose} disabled={parsing} className="flex-1">
              Cancel
            </Button>
            <Button
              onClick={handleParse}
              disabled={!canParse || parsing}
              className="flex-1 gap-2"
            >
              {parsing ? (
                <>
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Parsing with AI…
                </>
              ) : (
                'Parse Recipe'
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
