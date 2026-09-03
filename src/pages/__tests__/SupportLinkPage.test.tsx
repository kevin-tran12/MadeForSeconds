import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

vi.mock('../../hooks/useAuth', () => ({ useAuth: vi.fn() }))
vi.mock('../../lib/api', () => ({
  subscriberApi: { linkRequest: vi.fn(), linkConfirm: vi.fn() },
}))

import { useAuth } from '../../hooks/useAuth'
import { subscriberApi } from '../../lib/api'
import { SupportLinkPage } from '../SupportLinkPage'

const signedIn = { user: { email: 'reader@example.com' }, loginGoogle: vi.fn() }
const anonymous = { user: null, loginGoogle: vi.fn() }

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SupportLinkPage />
    </MemoryRouter>
  )
}

describe('SupportLinkPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('confirms the link automatically when the reader is signed in', async () => {
    vi.mocked(useAuth).mockReturnValue(signedIn as never)
    vi.mocked(subscriberApi.linkConfirm).mockResolvedValue({ message: 'Linked!', linked: 1, supporter: true })

    renderAt('/support/link/?token=abc')

    expect(await screen.findByText('Donation linked')).toBeDefined()
    expect(screen.getByText('Linked!')).toBeDefined()
    expect(subscriberApi.linkConfirm).toHaveBeenCalledWith('abc')
  })

  it('asks an anonymous reader to sign in before confirming', () => {
    vi.mocked(useAuth).mockReturnValue(anonymous as never)
    renderAt('/support/link/?token=abc')
    expect(screen.getByText('Sign in with Google to finish')).toBeDefined()
    expect(subscriberApi.linkConfirm).not.toHaveBeenCalled()
  })

  it('shows the failure and a way to request a new link', async () => {
    vi.mocked(useAuth).mockReturnValue(signedIn as never)
    vi.mocked(subscriberApi.linkConfirm).mockRejectedValue(new Error('Link has expired. Please request a new one.'))
    renderAt('/support/link/?token=old')
    expect(await screen.findByText('Linking failed')).toBeDefined()
    expect(screen.getByText('Link has expired. Please request a new one.')).toBeDefined()
    expect(screen.getByText('Request a new link')).toBeDefined()
  })

  it('requests a link for the checkout email', async () => {
    vi.mocked(useAuth).mockReturnValue(anonymous as never)
    vi.mocked(subscriberApi.linkRequest).mockResolvedValue({ message: 'ok' })
    const { container } = renderAt('/support/link/')

    fireEvent.change(screen.getByLabelText('Donation email'), { target: { value: 'donor@example.com' } })
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(subscriberApi.linkRequest).toHaveBeenCalledWith('donor@example.com'))
    expect(await screen.findByText('Check your email')).toBeDefined()
  })
})
