import type {
  Approval,
  Artifact,
  CodexAccount,
  CodexLogin,
  RoleSettings,
  RoleAssignment,
  Project,
  Run,
  RunEvent,
  RunReport,
  RunReference,
  SourceContent,
  SourceFile,
  Task,
  ToolCall,
} from './types'

async function request<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: string }
      detail = body.detail || detail
    } catch {
      // The status code remains useful when the response is not JSON.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  codexAccount: (token: string) => request<CodexAccount>('/api/codex/account', token),
  codexLogin: (token: string, method: 'browser' | 'device') =>
    request<CodexLogin>('/api/codex/login', token, {
      method: 'POST',
      body: JSON.stringify({ method }),
    }),
  codexLogout: (token: string) => request<{ connected: boolean }>('/api/codex/logout', token, { method: 'POST' }),
  roleSettings: (token: string) => request<RoleSettings>('/api/codex/roles', token),
  saveRoles: (token: string, assignments: Record<string, RoleAssignment>) => request<{ assignments: Record<string, RoleAssignment> }>('/api/codex/roles', token, { method: 'PUT', body: JSON.stringify({ assignments }) }),
  codexModels: (token: string) => request<{ models: string[] }>('/api/codex/models', token),
  projects: (token: string) => request<Project[]>('/api/projects', token),
  createProject: (token: string, name: string) =>
    request<Project>('/api/projects', token, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  deleteProject: (token: string, projectId: string) =>
    request<{ deleted: boolean; removed_runs: number; cleanup_failed: boolean }>(`/api/projects/${projectId}`, token, { method: 'DELETE' }),
  runs: (token: string, projectId: string) =>
    request<Run[]>(`/api/projects/${projectId}/runs`, token),
  createRun: (token: string, projectId: string, prompt: string, references: Array<{ name: string; data_base64: string }> = []) =>
    request<Run>(`/api/projects/${projectId}/runs`, token, {
      method: 'POST',
      body: JSON.stringify({ prompt, references }),
    }),
  references: (token: string, runId: string) => request<RunReference[]>(`/api/runs/${runId}/references`, token),
  terminalPreview: (token: string, runId: string, stdin: string) =>
    request<{ exit_code: number; stdout: string; stderr: string; duration_ms: number }>(`/api/runs/${runId}/preview/terminal`, token, {
      method: 'POST',
      body: JSON.stringify({ stdin }),
    }),
  run: (token: string, runId: string) => request<Run>(`/api/runs/${runId}`, token),
  tasks: (token: string, runId: string) => request<Task[]>(`/api/runs/${runId}/tasks`, token),
  events: (token: string, runId: string, after = 0) =>
    request<RunEvent[]>(`/api/runs/${runId}/events?after_seq=${after}`, token),
  tools: (token: string, runId: string) =>
    request<ToolCall[]>(`/api/runs/${runId}/tool-calls`, token),
  artifacts: (token: string, runId: string) =>
    request<Artifact[]>(`/api/runs/${runId}/artifacts`, token),
  approvals: (token: string, runId: string) =>
    request<Approval[]>(`/api/runs/${runId}/approvals`, token),
  files: (token: string, runId: string) =>
    request<SourceFile[]>(`/api/runs/${runId}/files`, token),
  file: (token: string, runId: string, path: string) =>
    request<SourceContent>(
      `/api/runs/${runId}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
      token,
    ),
  diff: (token: string, runId: string, path: string) =>
    request<{ path: string; diff: string }>(
      `/api/runs/${runId}/diff?path=${encodeURIComponent(path)}`,
      token,
    ),
  report: (token: string, runId: string) =>
    request<RunReport>(`/api/runs/${runId}/report`, token),
  control: (token: string, runId: string, action: 'pause' | 'resume' | 'cancel') =>
    request<Run>(`/api/runs/${runId}/${action}`, token, { method: 'POST' }),
  decide: (token: string, approvalId: string, decision: 'approve' | 'reject') =>
    request<{ id: string; status: string }>(`/api/approvals/${approvalId}/decision`, token, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  async download(token: string, runId: string): Promise<void> {
    const response = await fetch(`/api/runs/${runId}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new Error(`Không tải được mã nguồn (HTTP ${response.status})`)
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = `${runId}-source.zip`
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
}

export function runSocket(runId: string, afterSeq = 0): WebSocket {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return new WebSocket(`${scheme}//${location.host}/ws/runs/${runId}?after_seq=${afterSeq}`)
}
