import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

vi.mock('../../lib/auth', () => ({
  initAuth: vi.fn(),
  onAuthChange: vi.fn(),
  loginWithGoogle: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
}))
vi.mock('../../lib/api-client', () => ({ setTokenGetter: vi.fn(), clearTotpToken: vi.fn() }))
vi.mock('../../lib/api', () => ({ meApi: { get: vi.fn() } }))

import { onAuthChange } from '../../lib/auth'
import { meApi } from '../../lib/api'
import { AuthProvider, useAuthContext } from '../AuthContext'

function Probe() {
  const { isAdmin, isSupporter, meLoading, returning, firstName, refreshMe } = useAuthContext()
  return (
    <div>
      <span data-testid="admin">{isAdmin ? 'yes' : 'no'}</span>
      <span data-testid="supporter">{isSupporter ? 'yes' : 'no'}</span>
      <span data-testid="loading">{meLoading ? 'yes' : 'no'}</span>
      <span data-testid="returning">{returning ? 'yes' : 'no'}</span>
      <span data-testid="name">{firstName ?? '-'}</span>
      <button onClick={() => void refreshMe()}>refresh</button>
    </div>
  )
}

const profile = {
  email: 'kevin@example.com', is_admin: true, supporter: true, returning: true, answers_total: 3,
  cooking_experience: null,
  assistant: { supporter: true, day: { limit: 50, used: 0 }, month: { limit: 400, used: 0 }, remaining: 50, resets_at: '' },
}

describe('AuthContext (production mode)', () => {
  let emit: ((user: unknown) => void) | null = null

  beforeEach(() => {
    vi.stubEnv('DEV', false)
    vi.mocked(onAuthChange).mockImplementation((cb) => {
      emit = cb as (user: unknown) => void
      return () => {}
    })
    vi.mocked(meApi.get).mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('derives admin, supporter, and greeting from /api/me, not from being signed in', async () => {
    vi.mocked(meApi.get).mockResolvedValue(profile)
    render(<AuthProvider><Probe /></AuthProvider>)
    expect(screen.getByTestId('admin').textContent).toBe('no')

    act(() => emit!({ email: 'kevin@example.com', uid: 'u1', displayName: 'Kevin Tran' }))
    expect(screen.getByTestId('loading').textContent).toBe('yes')

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('no'))
    expect(screen.getByTestId('admin').textContent).toBe('yes')
    expect(screen.getByTestId('supporter').textContent).toBe('yes')
    expect(screen.getByTestId('returning').textContent).toBe('yes')
    expect(screen.getByTestId('name').textContent).toBe('Kevin')
    expect(meApi.get).toHaveBeenCalledTimes(1)
  })

  it('treats a signed-in reader the backend rejects as a plain reader', async () => {
    vi.mocked(meApi.get).mockRejectedValue(new Error('Invalid token'))
    render(<AuthProvider><Probe /></AuthProvider>)
    act(() => emit!({ email: 'reader@example.com', uid: 'u2', displayName: null }))
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('no'))
    expect(screen.getByTestId('admin').textContent).toBe('no')
    expect(screen.getByTestId('name').textContent).toBe('-')
  })

  it('refreshMe re-fetches and clears on sign-out', async () => {
    vi.mocked(meApi.get).mockResolvedValue({ ...profile, is_admin: false })
    render(<AuthProvider><Probe /></AuthProvider>)
    act(() => emit!({ email: 'reader@example.com', uid: 'u2', displayName: 'Ann Lee' }))
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('no'))

    vi.mocked(meApi.get).mockResolvedValue({ ...profile, is_admin: false, supporter: false })
    fireEvent.click(screen.getByText('refresh'))
    await waitFor(() => expect(screen.getByTestId('supporter').textContent).toBe('no'))
    expect(meApi.get).toHaveBeenCalledTimes(2)

    act(() => emit!(null))
    await waitFor(() => expect(screen.getByTestId('returning').textContent).toBe('no'))
    expect(screen.getByTestId('loading').textContent).toBe('no')
  })
})
