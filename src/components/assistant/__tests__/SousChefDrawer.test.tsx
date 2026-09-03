import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

vi.mock('../../../hooks/useAuth', () => ({ useAuth: vi.fn() }))
vi.mock('../../../lib/api', () => ({
  assistantApi: { status: vi.fn(), ask: vi.fn(), feedback: vi.fn() },
  meApi: { updateExperience: vi.fn(), deleteData: vi.fn() },
}))

import { useAuth } from '../../../hooks/useAuth'
import { assistantApi, meApi } from '../../../lib/api'
import { SousChefDrawer } from '../SousChefDrawer'
import type { Recipe } from '../../../lib/types'

const recipe = {
  id: 'r1', slug: 'laksa', title: 'Laksa', description: '', prep_time_minutes: 0, cook_time_minutes: 0,
  servings: 4, difficulty: 'easy', categories: [], image_url: null, published: true, nutrition: [],
  created_at: '', updated_at: '',
  ingredients: [{ item: 'rice noodles', amount: '200', unit: 'g' }, { item: 'prawns', amount: '12', unit: '' }],
  instructions: [{ step: 1, text: 'Cook.' }],
} as unknown as Recipe

const quota = { supporter: false, day: { limit: 5, used: 0 }, month: null, remaining: 5, resets_at: '2026-09-03T00:00:00+00:00' }
const status = { configured: true, paused: false, resets_at: '', quotas: { free: 5, supporter: 50, supporter_monthly: 400 }, levels: [] }
const experience = { level: 'confident', notes: '', updated_at: null }
const baseAuth = { meLoading: false, firstName: 'Kevin', returning: true, loginGoogle: vi.fn(), refreshMe: vi.fn().mockResolvedValue(undefined) }

function me(overrides: Record<string, unknown> = {}) {
  return { email: 'kevin@example.com', is_admin: false, supporter: false, returning: true, answers_total: 0, cooking_experience: experience, assistant: quota, ...overrides }
}

function renderDrawer(onClose = vi.fn()) {
  return render(
    <MemoryRouter>
      <SousChefDrawer recipe={recipe} servings={4} unitSystem="metric" onClose={onClose} />
    </MemoryRouter>
  )
}

describe('SousChefDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(assistantApi.status).mockResolvedValue(status)
  })

  it('shows the off notice when the backend has no key', async () => {
    vi.mocked(assistantApi.status).mockResolvedValue({ ...status, configured: false })
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: null, me: null } as never)
    renderDrawer()
    expect(await screen.findByText(/taking a break/i)).toBeDefined()
    expect(screen.queryByLabelText('Ask the Sous Chef')).toBeNull()
  })

  it('asks anonymous readers to sign in, with disabled example questions', async () => {
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: null, me: null } as never)
    renderDrawer()
    expect(await screen.findByText('Sign in with Google to ask')).toBeDefined()
    const chip = screen.getByText(/rice noodles/) as HTMLButtonElement
    expect(chip.disabled).toBe(true)
  })

  it('walks a first-time reader through their cooking experience and saves the skip default', async () => {
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: { email: 'k@x.y' }, me: me({ cooking_experience: null }) } as never)
    vi.mocked(meApi.updateExperience).mockResolvedValue({ cooking_experience: { level: 'home_cook', notes: '', updated_at: null } })
    renderDrawer()
    expect(await screen.findByText('How do you cook?')).toBeDefined()
    fireEvent.click(screen.getByText('Skip for now'))
    await waitFor(() => expect(meApi.updateExperience).toHaveBeenCalledWith('home_cook', ''))
    expect(baseAuth.refreshMe).toHaveBeenCalled()
  })

  it('points a free reader who is out of questions at the Support page', async () => {
    vi.mocked(useAuth).mockReturnValue({
      ...baseAuth, user: { email: 'k@x.y' }, me: me({ assistant: { ...quota, day: { limit: 5, used: 5 }, remaining: 0 } }),
    } as never)
    renderDrawer()
    expect(await screen.findByText(/used today's 5 free questions/i)).toBeDefined()
    expect(screen.getByText('Become a supporter').getAttribute('href')).toBe('/support/')
    expect(screen.getByText('Link that donation').getAttribute('href')).toBe('/support/link/')
  })

  it('asks the chef’s questions in a form and sends the answers back', async () => {
    const questions = [
      { text: 'Do you have a wok?', kind: 'equipment' },
      { text: 'What is your zip code?', kind: 'location' },
    ]
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: { email: 'k@x.y' }, me: me() } as never)
    vi.mocked(assistantApi.ask)
      .mockImplementationOnce(async (_body, onEvent) => {
        onEvent('meta', { quota })
        onEvent('clarify', { questions })
        onEvent('done', { usage: null, cost_micro_usd: 1, stop_reason: 'tool_use', truncated: false, refused: false, clarifying: true, quota })
      })
      .mockImplementationOnce(async (_body, onEvent) => {
        onEvent('delta', { text: 'Try the Asian grocer on your street.' })
        onEvent('done', { usage: null, cost_micro_usd: 1, stop_reason: 'end_turn', truncated: false, refused: false, clarifying: false, quota })
      })
    renderDrawer()

    const box = (await screen.findByLabelText('Ask the Sous Chef')) as HTMLTextAreaElement
    fireEvent.change(box, { target: { value: 'where do I buy holy basil?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('Do you have a wok?')).toBeDefined()
    expect(screen.queryByLabelText('Helpful')).toBeNull()  // nothing to rate yet

    const zip = screen.getByLabelText('What is your zip code?') as HTMLInputElement
    fireEvent.change(zip, { target: { value: 'San Francisco' } })
    expect(screen.getByText(/five-digit zip code/i)).toBeDefined()
    expect((screen.getByRole('button', { name: 'Answer' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(zip, { target: { value: '94110' } })
    fireEvent.click(screen.getByRole('button', { name: 'Answer' }))

    expect(await screen.findByText('Try the Asian grocer on your street.')).toBeDefined()
    const second = vi.mocked(assistantApi.ask).mock.calls[1][0]
    expect(second.context.clarified).toBe(true)
    expect(second.context.answers).toEqual([{ kind: 'location', text: '94110' }])
    expect(screen.queryByRole('button', { name: 'Answer' })).toBeNull()
  })

  it('shows where a searched answer came from', async () => {
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: { email: 'k@x.y' }, me: me({ supporter: true }) } as never)
    vi.mocked(assistantApi.ask).mockImplementation(async (_body, onEvent) => {
      onEvent('meta', { quota })
      onEvent('delta', { text: 'Belacan is a fermented shrimp paste.' })
      onEvent('sources', { sources: [{ url: 'https://weee.com/x', title: 'Weee! belacan' }] })
      onEvent('done', { usage: null, cost_micro_usd: 1, stop_reason: 'end_turn', truncated: false, refused: false, clarifying: false, searches: 1, quota })
    })
    renderDrawer()

    const box = await screen.findByLabelText('Ask the Sous Chef')
    fireEvent.change(box, { target: { value: 'what is belacan?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    const link = (await screen.findByText('Weee! belacan')) as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('https://weee.com/x')
    expect(link.getAttribute('rel')).toBe('noopener nofollow')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(screen.getByText('Sources')).toBeDefined()
  })

  it('says what it is doing while it searches', async () => {
    let finish: () => void = () => {}
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: { email: 'k@x.y' }, me: me() } as never)
    vi.mocked(assistantApi.ask).mockImplementation(async (_body, onEvent) => {
      onEvent('meta', { quota })
      onEvent('status', { state: 'searching' })
      await new Promise<void>((resolve) => { finish = resolve })
    })
    renderDrawer()

    const box = await screen.findByLabelText('Ask the Sous Chef')
    fireEvent.change(box, { target: { value: 'where do I buy belacan?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('Checking sources…')).toBeDefined()
    finish()
    await waitFor(() => expect(screen.queryByText('Checking sources…')).toBeNull())
  })

  it('warns about personal details and puts the question back in the composer', async () => {
    const { ApiError } = await import('../../../lib/api-client')
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: { email: 'k@x.y' }, me: me() } as never)
    vi.mocked(assistantApi.ask).mockRejectedValue(
      new ApiError(400, { code: 'personal_info', kind: 'phone', message: 'Please don’t share personal details like phone numbers.' })
    )
    renderDrawer()

    const box = (await screen.findByLabelText('Ask the Sous Chef')) as HTMLTextAreaElement
    fireEvent.change(box, { target: { value: 'call me on 415-555-0100 about the laksa' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText(/don.t share personal details/i)).toBeDefined()
    await waitFor(() => expect(box.value).toBe('call me on 415-555-0100 about the laksa'))
    // Not left in the transcript: the starter chips are still what's on screen.
    expect(screen.getByText(/I don't have rice noodles/)).toBeDefined()
  })

  it('greets a returning reader, streams an answer from a starter chip, and takes feedback', async () => {
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: { email: 'k@x.y' }, me: me() } as never)
    vi.mocked(assistantApi.ask).mockImplementation(async (body, onEvent) => {
      onEvent('meta', { quota: { ...quota, day: { limit: 5, used: 1 }, remaining: 4 } })
      onEvent('delta', { text: 'Rice vermicelli works; ' })
      onEvent('delta', { text: 'soak it first.' })
      onEvent('done', { usage: null, cost_micro_usd: 1, stop_reason: 'end_turn', truncated: false, refused: false, quota: { ...quota, day: { limit: 5, used: 1 }, remaining: 4 } })
    })
    vi.mocked(assistantApi.feedback).mockResolvedValue({ recorded: true })
    renderDrawer()

    expect(await screen.findByText(/Welcome back, Kevin/)).toBeDefined()
    expect(screen.getByText('Confident')).toBeDefined()
    fireEvent.click(screen.getByText(/I don't have rice noodles/))

    expect(await screen.findByText('Rice vermicelli works; soak it first.')).toBeDefined()
    const body = vi.mocked(assistantApi.ask).mock.calls[0][0]
    expect(body.slug).toBe('laksa')
    expect(body.context).toEqual({ servings: 4, unit_system: 'metric' })
    expect(screen.getByText('4 of 5 today')).toBeDefined()

    fireEvent.click(screen.getByLabelText('Not helpful'))
    await waitFor(() => expect(assistantApi.feedback).toHaveBeenCalledWith(expect.objectContaining({ rating: 'down', answer: 'Rice vermicelli works; soak it first.' })))
    expect(screen.getByText(/that helps the chef/)).toBeDefined()
  })

  it('closes on Escape and on the close button', async () => {
    vi.mocked(useAuth).mockReturnValue({ ...baseAuth, user: null, me: null } as never)
    const onClose = vi.fn()
    renderDrawer(onClose)
    await screen.findByText('Sign in with Google to ask')
    fireEvent.keyDown(window, { key: 'Escape' })
    fireEvent.click(screen.getByLabelText('Close Sous Chef'))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
