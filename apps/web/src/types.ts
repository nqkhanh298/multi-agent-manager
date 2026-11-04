export type RunStatus =
  | 'CREATED'
  | 'PLANNING'
  | 'RUNNING'
  | 'PAUSED'
  | 'WAITING_APPROVAL'
  | 'BLOCKED'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export type TaskStatus =
  | 'PENDING'
  | 'READY'
  | 'RUNNING'
  | 'VERIFYING'
  | 'COMPLETED'
  | 'FAILED'
  | 'BLOCKED'
  | 'CANCELLED'

export interface Project {
  id: string
  name: string
  description: string
  created_at: string
}

export interface Run {
  id: string
  project_id: string
  prompt: string
  engine?: 'demo' | 'codex' | 'codex_web' | 'codex_auto'
  status: RunStatus
  control_request?: 'pause' | 'cancel' | null
  version: number
  created_at: string
  updated_at: string
  report_ref: string | null
  budget_usd?: number | null
  spent_usd?: number | null
  max_seconds?: number
}

export interface RunReference {
  id: string
  name: string
  sha256: string
  chars: number
  text: string
}

export interface ReferenceCheck {
  id: string
  quote: string
  file: string
  evidence: string
}

export interface CodexAccount {
  connected: boolean
  email: string | null
  plan_type: string | null
}

export interface CodexLogin {
  login_id: string | null
  auth_url: string | null
  verification_url: string | null
  user_code: string | null
}

export type RoleAssignment = { provider: 'codex'; model: string }
export type RoleSettings = { assignments: Record<string, RoleAssignment> }

export interface Task {
  id: string
  title: string
  agent_role: string
  model?: string | null
  status: TaskStatus
  depends_on: string[]
  workspace_ref: string | null
  duration_ms?: number | null
  input_tokens?: number
  output_tokens?: number
  cost_usd?: number
}

export interface RunEvent {
  event_id: string
  run_id: string
  sequence: number
  type: string
  payload: Record<string, unknown>
  timestamp: string
}

export interface ToolCall {
  task_id: string
  idempotency_key: string
  name: string
  arguments: Record<string, unknown>
  status: string
  exit_code: number | null
}

export interface Artifact {
  id: string
  path: string
  sha256: string
  size: number
}

export interface Approval {
  id: string
  action: string
  payload: Record<string, unknown>
  status: string
}

export interface SourceFile {
  path: string
  size: number
}

export interface SourceContent {
  path: string
  content: string
}

export interface RunReport {
  target?: 'web' | 'python_cli' | null
  status: string
  reason?: string
  parallel_overlap_ms: number
  tasks: Array<{ task_id: string; status: string; test_stdout: string; reason: string }>
  merges: Array<{ task_id: string; status: string; commit?: string }>
  integration: Record<string, string | number>
  reference_checks?: ReferenceCheck[]
}
