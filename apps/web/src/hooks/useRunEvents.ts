import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { runSocket } from '../api'
import type { RunEvent } from '../types'

export function useRunEvents(token: string, runId: string | null) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!token || !runId) return
    let disposed = false
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let lastSeq = Math.max(
      0,
      ...(queryClient.getQueryData<RunEvent[]>(['events', runId]) || []).map((item) => item.sequence),
    )

    function connect() {
      if (disposed || !runId) return
      socket = runSocket(runId, lastSeq)
      socket.onopen = () => socket?.send(JSON.stringify({ token }))
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data as string) as RunEvent
        if (event.sequence <= lastSeq) return
        lastSeq = event.sequence
        queryClient.setQueryData<RunEvent[]>(['events', runId], (old = []) =>
          [...old.filter((item) => item.sequence !== event.sequence), event].sort(
            (a, b) => a.sequence - b.sequence,
          ),
        )
        for (const key of ['run', 'tasks', 'tools', 'report', 'files', 'artifacts', 'approvals']) {
          void queryClient.invalidateQueries({ queryKey: [key, runId] })
        }
      }
      socket.onclose = () => {
        if (!disposed) timer = setTimeout(connect, 1800)
      }
    }
    connect()
    return () => {
      disposed = true
      if (timer) clearTimeout(timer)
      socket?.close()
    }
  }, [token, runId, queryClient])
}
