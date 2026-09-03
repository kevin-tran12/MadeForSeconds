import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

vi.mock('../../hooks/useAuth', () => ({ useAuth: vi.fn() }))
vi.mock('../../lib/api', () => ({
  subscriberApi: { createCheckout: vi.fn() },
}))

import { useAuth } from '../../hooks/useAuth'
import { SupportPage } from '../SupportPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <SupportPage />
    </MemoryRouter>
  )
}

describe('SupportPage account link', () => {
  it('tells a signed-in reader the donation is linked to their account', () => {
    vi.mocked(useAuth).mockReturnValue({ user: { email: 'reader@example.com' }, loginGoogle: vi.fn() } as never)
    renderPage()
    expect(screen.getByText('reader@example.com')).toBeDefined()
    expect(screen.getByText(/linked to your account/i)).toBeDefined()
    expect(screen.queryByText('Sign in with Google')).toBeNull()
  })

  it('offers an optional Google sign-in to anonymous readers', () => {
    vi.mocked(useAuth).mockReturnValue({ user: null, loginGoogle: vi.fn() } as never)
    renderPage()
    expect(screen.getByText('Sign in with Google')).toBeDefined()
    expect(screen.getByText('Link it to your account')).toBeDefined()
  })
})
