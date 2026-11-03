import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('API client', () => {
  it('sends the bearer token only in the header', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetchMock)
    await api.events('local-secret', 'run-1', 4)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/runs/run-1/events?after_seq=4',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer local-secret' }) }),
    )
    expect(fetchMock.mock.calls[0][0]).not.toContain('local-secret')
  })

  it('reports server errors to the UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'run not found' }) }))
    await expect(api.run('token', 'missing')).rejects.toThrow('run not found')
  })
})
