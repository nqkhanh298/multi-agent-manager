import { create } from 'zustand'

interface UIState {
  token: string
  projectId: string | null
  runId: string | null
  taskId: string | null
  filePath: string | null
  workspaceTab: 'code' | 'diff' | 'tests' | 'logs' | 'preview'
  setToken: (token: string) => void
  setProject: (id: string | null) => void
  setRun: (id: string | null) => void
  setTask: (id: string | null) => void
  setFile: (path: string | null) => void
  setWorkspaceTab: (tab: 'code' | 'diff' | 'tests' | 'logs' | 'preview') => void
}

export const useUI = create<UIState>((set) => ({
  token: sessionStorage.getItem('m5-api-token') || '',
  projectId: null,
  runId: null,
  taskId: null,
  filePath: null,
  workspaceTab: 'code',
  setToken: (token) => {
    if (token) sessionStorage.setItem('m5-api-token', token)
    else sessionStorage.removeItem('m5-api-token')
    set({ token, projectId: null, runId: null, taskId: null, filePath: null })
  },
  setProject: (projectId) => set({ projectId, runId: null, taskId: null, filePath: null }),
  setRun: (runId) => set({ runId, taskId: null, filePath: null }),
  setTask: (taskId) => set({ taskId }),
  setFile: (filePath) => set({ filePath }),
  setWorkspaceTab: (workspaceTab) => set({ workspaceTab }),
}))
