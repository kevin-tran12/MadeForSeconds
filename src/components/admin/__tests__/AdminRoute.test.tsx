import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import React from 'react'

vi.mock('../../../hooks/useAuth', () => ({ useAuth: vi.fn() }))

import { useAuth } from '../../../hooks/useAuth'
import { AdminRoute } from '../AdminRoute'

const base = { loginGoogle: vi.fn(), devLogin: vi.fn(), logout: vi.fn() }

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={['/admin/']}>
      <Routes>
        <Route path="/admin/" element={<AdminRoute />}>
          <Route index element={<div>dashboard</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

describe('AdminRoute', () => {
  it('shows the login modal to anonymous visitors', () => {
    vi.mocked(useAuth).mockReturnValue({ ...base, user: null, isAdmin: false, meLoading: false } as never)
    renderRoute()
    expect(screen.getByText('Admin Login')).toBeDefined()
    expect(screen.queryByText('dashboard')).toBeNull()
  })

  it('waits for the backend verdict before deciding', () => {
    vi.mocked(useAuth).mockReturnValue({ ...base, user: { email: 'x@y.z' }, isAdmin: false, meLoading: true } as never)
    renderRoute()
    expect(screen.queryByText('dashboard')).toBeNull()
    expect(screen.queryByText(/isn't an admin/)).toBeNull()
  })

  it('tells a signed-in reader this account is not an admin, with a way out', () => {
    vi.mocked(useAuth).mockReturnValue({ ...base, user: { email: 'reader@example.com' }, isAdmin: false, meLoading: false } as never)
    renderRoute()
    expect(screen.getByText(/isn't an admin/)).toBeDefined()
    expect(screen.getByText('reader@example.com')).toBeDefined()
    expect(screen.getByText('Log out')).toBeDefined()
    expect(screen.queryByText('dashboard')).toBeNull()
  })

  it('renders the admin area for an admin', () => {
    vi.mocked(useAuth).mockReturnValue({ ...base, user: { email: 'kevin@example.com' }, isAdmin: true, meLoading: false } as never)
    renderRoute()
    expect(screen.getByText('dashboard')).toBeDefined()
  })
})
