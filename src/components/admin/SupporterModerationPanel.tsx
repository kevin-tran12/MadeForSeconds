import { useState, useEffect, useCallback } from 'react'
import { adminSupporterApi, type PendingSupporter, type AdminSupporter } from '../../lib/api'
import { Button } from '../ui/Button'

function dollars(cents: number) {
  return `$${(cents / 100).toFixed(0)}`
}

export function SupporterModerationPanel() {
  const [pending, setPending] = useState<PendingSupporter[]>([])
  const [all, setAll] = useState<AdminSupporter[]>([])
  const [loading, setLoading] = useState(true)
  const [actionStatus, setActionStatus] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, a] = await Promise.all([
        adminSupporterApi.listPending(),
        adminSupporterApi.listAll(),
      ])
      setPending(p)
      setAll(a)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function flash(id: string, msg: string) {
    setActionStatus((prev) => ({ ...prev, [id]: msg }))
    setTimeout(() => setActionStatus((prev) => {
      const n = { ...prev }; delete n[id]; return n
    }), 2000)
  }

  async function handleApprove(s: PendingSupporter) {
    await adminSupporterApi.approveNote(s.collection, s.id)
    setPending((prev) => prev.filter((p) => p.id !== s.id))
    setAll((prev) => prev.map((a) =>
      a.id === s.id
        ? { ...a, note: s.note_pending, note_is_public: s.note_pending_public, note_pending: null }
        : a
    ))
    flash(s.id, '✓ Approved')
  }

  async function handleReject(s: PendingSupporter) {
    await adminSupporterApi.rejectNote(s.collection, s.id)
    setPending((prev) => prev.filter((p) => p.id !== s.id))
    flash(s.id, 'Rejected')
  }

  async function handleToggleName(s: AdminSupporter) {
    const { name_enabled } = await adminSupporterApi.toggleName(s.collection, s.id)
    setAll((prev) => prev.map((a) => a.id === s.id ? { ...a, name_enabled } : a))
  }

  async function handleToggleNote(s: AdminSupporter) {
    const { note_enabled } = await adminSupporterApi.toggleNote(s.collection, s.id)
    setAll((prev) => prev.map((a) => a.id === s.id ? { ...a, note_enabled } : a))
  }

  if (loading) {
    return <p className="text-sm text-gray-500 py-8 text-center">Loading supporters...</p>
  }

  return (
    <div className="space-y-8">

      {/* Pending notes */}
      {pending.length > 0 && (
        <section>
          <h2 className="text-xs font-bold uppercase tracking-widest text-amber-600 mb-3">
            Pending notes — {pending.length}
          </h2>
          <div className="rounded-xl border border-amber-200 bg-amber-50 divide-y divide-amber-100">
            {pending.map((s) => (
              <div key={s.id} className="flex items-start justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-800">
                    {s.display_name || <span className="italic text-gray-400">No name set</span>}
                    <span className="ml-2 text-xs font-normal text-gray-400">{s.email}</span>
                  </p>
                  <p className="mt-0.5 text-sm text-gray-700">
                    &ldquo;{s.note_pending}&rdquo;
                    <span className="ml-2 text-xs text-gray-400">
                      {s.note_pending_public ? 'Public' : 'Private'}
                    </span>
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {actionStatus[s.id] ? (
                    <span className="text-xs font-medium text-green-600">{actionStatus[s.id]}</span>
                  ) : (
                    <>
                      <Button size="sm" onClick={() => handleApprove(s)}>Approve</Button>
                      <Button size="sm" variant="danger" onClick={() => handleReject(s)}>Reject</Button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* All supporters */}
      <section>
        <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">
          All supporters — {all.length}
        </h2>
        {all.length === 0 ? (
          <p className="text-sm text-gray-400">No supporters with display names yet.</p>
        ) : (
          <div className="rounded-xl border border-gray-200 bg-white divide-y divide-gray-100">
            {all.map((s) => (
              <div key={s.id} className="flex items-start justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <p className={`text-sm font-semibold ${s.name_enabled ? 'text-gray-800' : 'text-gray-400 line-through'}`}>
                    {s.display_name}
                    <span className={`ml-2 text-xs font-normal ${s.name_enabled ? 'text-gray-400' : 'text-gray-300'}`}>
                      {s.email} · {dollars(s.total_donated_cents)} · {s.status}
                    </span>
                  </p>
                  {s.note ? (
                    <p className={`mt-0.5 text-sm italic ${s.note_enabled ? 'text-gray-500' : 'text-gray-300 line-through'}`}>
                      &ldquo;{s.note}&rdquo;
                      <span className="ml-1 not-italic text-xs text-gray-400">
                        ({s.note_is_public ? 'public' : 'private'})
                      </span>
                    </p>
                  ) : (
                    <p className="mt-0.5 text-xs text-gray-400">No live note</p>
                  )}
                  {s.note_pending && (
                    <p className="mt-0.5 text-xs text-amber-600">Note pending approval</p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {/* Note toggle */}
                  {s.note && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleToggleNote(s)}
                    >
                      {s.note_enabled ? 'Hide note' : 'Show note'}
                    </Button>
                  )}
                  {/* Name toggle */}
                  <Button
                    size="sm"
                    variant={s.name_enabled ? 'secondary' : 'primary'}
                    onClick={() => handleToggleName(s)}
                  >
                    {s.name_enabled ? 'Hide' : 'Show'}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

    </div>
  )
}
