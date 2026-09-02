import { describe, it, expect } from 'vitest'
import { parseSse } from '../sse'

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

async function collect(chunks: string[]) {
  const events: [string, string][] = []
  await parseSse(streamOf(chunks), (event, data) => events.push([event, data]))
  return events
}

describe('parseSse', () => {
  it('parses two events arriving in one chunk', async () => {
    const events = await collect(['event: meta\ndata: {"a":1}\n\nevent: delta\ndata: {"text":"hi"}\n\n'])
    expect(events).toEqual([
      ['meta', '{"a":1}'],
      ['delta', '{"text":"hi"}'],
    ])
  })

  it('reassembles an event split across chunks, including mid-multibyte', async () => {
    const whole = 'event: delta\ndata: {"text":"crème brûlée"}\n\n'
    const bytes = new TextEncoder().encode(whole)
    const cut = 30 // lands inside "crème"
    const a = new TextDecoder().decode(bytes.slice(0, cut))
    // Rebuild chunks from raw bytes so the split is genuinely mid-character.
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut))
        controller.enqueue(bytes.slice(cut))
        controller.close()
      },
    })
    const events: [string, string][] = []
    await parseSse(stream, (e, d) => events.push([e, d]))
    expect(a.length).toBeGreaterThan(0)
    expect(events).toEqual([['delta', '{"text":"crème brûlée"}']])
  })

  it('joins multi-line data, ignores comments, and defaults the event name', async () => {
    const events = await collect([': keep-alive\n', 'data: line one\ndata: line two\n\n', 'event: done\ndata: {}\n\n'])
    expect(events).toEqual([
      ['message', 'line one\nline two'],
      ['done', '{}'],
    ])
  })

  it('flushes a final event with no trailing blank line and tolerates CRLF', async () => {
    const events = await collect(['event: error\r\ndata: {"code":"x"}'])
    expect(events).toEqual([['error', '{"code":"x"}']])
  })
})
