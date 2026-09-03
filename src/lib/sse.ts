/**
 * Minimal Server-Sent Events parser over a fetch() body.
 *
 * Why not EventSource: it is GET-only and cannot carry the Authorization
 * header the Sous Chef endpoint needs. A streamed POST plus this parser gives
 * the same event/data framing with the normal apiFetch header injection.
 */
export async function parseSse(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: string) => void
): Promise<void> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (block: string) => {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue // comment / keep-alive
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (data.length > 0) onEvent(event, data.join('\n'))
  }

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (block.trim()) dispatch(block)
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
  } finally {
    reader.releaseLock()
  }
}
