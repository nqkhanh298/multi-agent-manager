import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, ArrowRight, Bell, Bot, Check, ChevronRight, CircleCheck, Clock3,
  Download, FolderPlus, LayoutDashboard, LogOut, Paperclip, Pause, Play, Plus,
  Send, ShieldCheck, Square, Trash2, Workflow as WorkflowIcon, X,
} from 'lucide-react'
import { api } from './api'
import { Login } from './components/Login'
import { CodexConnection, useCodexAccount } from './components/CodexConnection'
import { RoleSettings } from './components/RoleSettings'
import { AgentActivity } from './components/AgentActivity'
import { ProjectList } from './components/ProjectList'
import { Workflow } from './components/Workflow'
import { Workspace } from './components/Workspace'
import { RunReferences } from './components/RunReferences'
import { useRunEvents } from './hooks/useRunEvents'
import { useUI } from './store'
import type { Project, RunEvent, Task } from './types'

const statusNames: Record<string, string> = {
  CREATED: 'Đang chờ', PLANNING: 'Lập kế hoạch', RUNNING: 'Đang chạy',
  PAUSED: 'Tạm dừng', WAITING_APPROVAL: 'Chờ phê duyệt', BLOCKED: 'Bị chặn',
  COMPLETED: 'Hoàn thành', FAILED: 'Thất bại', CANCELLED: 'Đã hủy',
  PENDING: 'Chưa bắt đầu', READY: 'Sẵn sàng', VERIFYING: 'Đang kiểm tra',
}

const roleNames: Record<string, string> = {
  backend_dev: 'Backend Dev', frontend_dev: 'Frontend Dev', qa: 'QA',
  coordinator: 'Coordinator', researcher: 'Researcher', architect: 'Architect',
  designer: 'Designer', developer: 'Developer', writer: 'Writer', release: 'Release',
}

function statusClass(status: string): string {
  return `status-${status.toLowerCase()}`
}

function recentEvent(event: RunEvent): string {
  if (event.type === 'references.attached') return 'Đã lưu tài liệu tham chiếu cho lượt chạy'
  if (event.type === 'references.injected') return `Đã gửi tài liệu cho ${String(event.payload.role)}`
  if (event.type === 'references.verified') return 'QA đã đối chiếu tài liệu với mã nguồn'
  if (event.type === 'references.review_failed') return `Đối chiếu tài liệu thất bại: ${String(event.payload.reason || '')}`
  if (event.type === 'run.status') return `Lượt chạy: ${statusNames[String(event.payload.to)] || String(event.payload.to)}`
  if (event.type === 'task.merge') return `${event.payload.task_id} đã ${event.payload.status === 'MERGED' ? 'merge' : 'gặp xung đột'}`
  if (event.type === 'task.status') return `${event.payload.task_id}: ${statusNames[String(event.payload.status)] || event.payload.status}`
  if (event.type === 'task.model') return `${event.payload.task_id}: đang dùng model ${String(event.payload.model)}`
  if (event.type === 'task.activity') return `${event.payload.task_id}: ${String(event.payload.detail || '')}`
  if (event.type === 'run.target_activity') return String(event.payload.detail || 'Đang chọn cách tạo ứng dụng')
  if (event.type === 'run.target_selected') return event.payload.target === 'research_report' ? 'Đã chọn báo cáo nghiên cứu' : event.payload.target === 'web' ? 'Đã chọn ứng dụng có giao diện' : 'Đã chọn ứng dụng terminal'
  if (event.type === 'run.plan') return `Coordinator đã chọn ${Array.isArray(event.payload.tasks) ? event.payload.tasks.length : 0} agent phù hợp`
  if (event.type === 'artifact.ready') return 'Mã nguồn đã sẵn sàng để tải'
  if (event.type === 'tool.started') return `${event.payload.task_id} đang chạy ${event.payload.tool}`
  if (event.type === 'tool.completed') return `${event.payload.task_id} đã xong ${event.payload.tool}`
  return event.type
}

function encodeReference(file: File): Promise<{ name: string; data_base64: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`Không đọc được ${file.name}`))
    reader.onload = () => resolve({ name: file.name, data_base64: String(reader.result).split(',')[1] || '' })
    reader.readAsDataURL(file)
  })
}

const SOURCE_SUFFIX = /\.(txt|md|csv|json|py|js|jsx|ts|tsx|html|css|scss|vue|svelte|yaml|yml|toml|sql|go|rs|java|kt|c|cpp|h|cs|php|rb|sh|bat|ps1|xml)$/i
const SOURCE_IGNORED = new Set(['.git', 'node_modules', 'dist', 'build', '.venv', 'venv', '__pycache__', 'coverage'])
const SOURCE_BASENAMES = new Set(['Dockerfile', 'Makefile', 'Procfile', 'Gemfile'])

function sourcePath(file: File): string { return file.webkitRelativePath || `source/${file.name}` }

function isSourceFile(file: File): boolean {
  const parts = sourcePath(file).split('/')
  return (SOURCE_SUFFIX.test(file.name) || SOURCE_BASENAMES.has(file.name)) && parts.every((part) => !part.startsWith('.') && !SOURCE_IGNORED.has(part.toLowerCase()))
}

async function encodeSourceFile(file: File): Promise<{ path: string; data_base64: string }> {
  const encoded = await encodeReference(file)
  return { path: sourcePath(file), data_base64: encoded.data_base64 }
}

function App() {
  const token = useUI((state) => state.token)
  return token ? <Studio token={token} /> : <Login />
}

function Studio({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const projectId = useUI((state) => state.projectId)
  const runId = useUI((state) => state.runId)
  const taskId = useUI((state) => state.taskId)
  const setProject = useUI((state) => state.setProject)
  const setRun = useUI((state) => state.setRun)
  const setTask = useUI((state) => state.setTask)
  const setWorkspaceTab = useUI((state) => state.setWorkspaceTab)
  const setToken = useUI((state) => state.setToken)
  const [prompt, setPrompt] = useState('')
  const [referenceFiles, setReferenceFiles] = useState<File[]>([])
  const [sourceFiles, setSourceFiles] = useState<File[]>([])
  const [newProject, setNewProject] = useState('')
  const [showProjectForm, setShowProjectForm] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [showApproval, setShowApproval] = useState(false)
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null)

  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: () => api.projects(token), retry: false })
  const codexAccount = useCodexAccount(token)
  const runsQuery = useQuery({ queryKey: ['runs', projectId], queryFn: () => api.runs(token, projectId!), enabled: Boolean(projectId), refetchInterval: 4000 })
  const runQuery = useQuery({ queryKey: ['run', runId], queryFn: () => api.run(token, runId!), enabled: Boolean(runId), refetchInterval: 2000 })
  const tasksQuery = useQuery({ queryKey: ['tasks', runId], queryFn: () => api.tasks(token, runId!), enabled: Boolean(runId), refetchInterval: 2000 })
  const taskActivityQuery = useQuery({
    queryKey: ['task-activity', runId, taskId],
    queryFn: () => api.taskActivity(token, runId!, taskId!),
    enabled: Boolean(runId && taskId),
    refetchInterval: runQuery.data?.status === 'RUNNING' ? 2000 : false,
  })
  const eventsQuery = useQuery({ queryKey: ['events', runId], queryFn: () => api.events(token, runId!), enabled: Boolean(runId), refetchInterval: 5000 })
  const filesQuery = useQuery({ queryKey: ['files', runId], queryFn: () => api.files(token, runId!), enabled: Boolean(runId), refetchInterval: 3000 })
  const reportQuery = useQuery({ queryKey: ['report', runId], queryFn: () => api.report(token, runId!), enabled: Boolean(runId), retry: false, refetchInterval: 4000 })
  const referencesQuery = useQuery({ queryKey: ['references', runId], queryFn: () => api.references(token, runId!), enabled: Boolean(runId) })
  const artifactsQuery = useQuery({ queryKey: ['artifacts', runId], queryFn: () => api.artifacts(token, runId!), enabled: Boolean(runId), refetchInterval: 4000 })
  const approvalsQuery = useQuery({ queryKey: ['approvals', runId], queryFn: () => api.approvals(token, runId!), enabled: Boolean(runId), refetchInterval: 4000 })
  useRunEvents(token, runId)

  useEffect(() => {
    if (!projectId && projectsQuery.data?.length) setProject(projectsQuery.data[0].id)
  }, [projectId, projectsQuery.data, setProject])
  useEffect(() => {
    if (!runId && runsQuery.data?.length) setRun(runsQuery.data[0].id)
  }, [runId, runsQuery.data, setRun])
  useEffect(() => {
    if (!taskId && tasksQuery.data?.length) setTask(tasksQuery.data[0].id)
  }, [taskId, tasksQuery.data, setTask])

  const projects = projectsQuery.data || []
  const runs = runsQuery.data || []
  const run = runQuery.data || runs.find((item) => item.id === runId)
  const tasks = tasksQuery.data || []
  const events = eventsQuery.data || []
  const files = filesQuery.data || []
  const selectedProject = projects.find((item) => item.id === projectId)
  const selectedTask = tasks.find((item) => item.id === taskId)
  const completed = tasks.filter((task) => task.status === 'COMPLETED').length
  const progress = tasks.length ? Math.round((completed / tasks.length) * 100) : 0
  const pendingApprovals = (approvalsQuery.data || []).filter((item) => item.status === 'PENDING')
  const latestEvents = useMemo(() => [...events].reverse().slice(0, 6), [events])

  async function createProject(event: FormEvent) {
    event.preventDefault()
    if (!newProject.trim()) return
    setBusy('project')
    setError('')
    try {
      const project = await api.createProject(token, newProject.trim())
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      setProject(project.id)
      setNewProject('')
      setShowProjectForm(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không tạo được dự án')
    } finally { setBusy('') }
  }

  async function deleteProject() {
    if (!projectToDelete) return
    const target = projectToDelete
    setBusy('delete-project')
    setError('')
    try {
      const result = await api.deleteProject(token, target.id)
      const remaining = (projectsQuery.data || []).filter((project) => project.id !== target.id)
      queryClient.setQueryData(['projects'], remaining)
      queryClient.removeQueries({ queryKey: ['runs', target.id] })
      if (projectId === target.id) setProject(remaining[0]?.id || null)
      setProjectToDelete(null)
      if (result.cleanup_failed) setError('Dự án đã xóa, nhưng một số file kết quả cục bộ chưa xóa được.')
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không xóa được dự án')
    } finally { setBusy('') }
  }

  async function createRun(event: FormEvent) {
    event.preventDefault()
    if (!projectId || !prompt.trim()) return
    setBusy('run')
    setError('')
    try {
      const references = await Promise.all(referenceFiles.map(encodeReference))
      const source = await Promise.all(sourceFiles.map(encodeSourceFile))
      const created = await api.createRun(token, projectId, prompt.trim(), references, source)
      await queryClient.invalidateQueries({ queryKey: ['runs', projectId] })
      setRun(created.id)
      setWorkspaceTab('preview')
      setPrompt('')
      setReferenceFiles([])
      setSourceFiles([])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không bắt đầu được lượt chạy')
    } finally { setBusy('') }
  }

  function addReferenceFiles(files: FileList | null) {
    if (!files) return
    const next = [...referenceFiles, ...Array.from(files)]
    if (next.length > 3) { setError('Chỉ đính kèm tối đa 3 tài liệu.'); return }
    if (next.some((file) => !/\.(pdf|docx|txt|md|csv|json)$/i.test(file.name) || file.size > 2_000_000)) {
      setError('Chỉ hỗ trợ PDF, DOCX, TXT, MD, CSV, JSON; mỗi tệp tối đa 2 MB.')
      return
    }
    setError('')
    setReferenceFiles(next)
  }

  function addSourceFolder(files: FileList | null) {
    if (!files) return
    const selected = Array.from(files).filter(isSourceFile)
    const total = selected.reduce((sum, file) => sum + file.size, 0)
    if (!selected.length) { setError('Thư mục không có file source dạng văn bản được hỗ trợ.'); return }
    if (selected.length > 40 || total > 2_000_000 || selected.some((file) => file.size > 48_000)) {
      setError('Source tham chiếu tối đa 40 file, 2 MB tổng cộng và khoảng 12.000 ký tự mỗi file. Hãy chọn thư mục nhỏ hơn.')
      return
    }
    setSourceFiles(selected)
    setError('')
  }

  async function control(action: 'pause' | 'resume' | 'cancel') {
    if (!runId) return
    setBusy(action)
    setError('')
    try {
      const updated = await api.control(token, runId, action)
      queryClient.setQueryData(['run', runId], updated)
      await queryClient.invalidateQueries({ queryKey: ['run', runId] })
      await queryClient.invalidateQueries({ queryKey: ['events', runId] })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không điều khiển được lượt chạy')
    } finally { setBusy('') }
  }

  async function decide(approvalId: string, decision: 'approve' | 'reject') {
    setBusy('approval')
    setError('')
    try {
      await api.decide(token, approvalId, decision)
      await queryClient.invalidateQueries({ queryKey: ['approvals', runId] })
      setShowApproval(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không gửi được quyết định')
    } finally { setBusy('') }
  }

  async function download() {
    if (!runId) return
    setBusy('download')
    setError('')
    try { await (reportQuery.data?.target === 'research_report' ? api.downloadReport(token, runId) : api.download(token, runId)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Không tải được mã nguồn') }
    finally { setBusy('') }
  }

  if (projectsQuery.isError) {
    return <div className="fatal-error"><h1>Không kết nối được API</h1><p>{projectsQuery.error.message}</p><button onClick={() => setToken('')}>Nhập lại token</button></div>
  }

  return (
    <div className="studio-shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><span className="brand-mark"><Bot size={24} /></span><span><strong>AI Coding Studio</strong><small>Multi-Agent Platform</small></span></div>
        <div className="sidebar-section-title">KHÔNG GIAN LÀM VIỆC</div>
        <button className="nav-item active"><LayoutDashboard size={17} /> Dự án <ChevronRight size={14} /></button>
        <div className="sidebar-section-header"><span>Dự án của tôi</span><button aria-label="Tạo dự án" title="Tạo dự án" onClick={() => setShowProjectForm(!showProjectForm)}><Plus size={17} /></button></div>
        {showProjectForm && <form className="new-project-form" onSubmit={createProject}><input aria-label="Tên dự án mới" value={newProject} onChange={(event) => setNewProject(event.target.value)} placeholder="Tên dự án…" autoFocus /><button type="submit" disabled={busy === 'project'}><ArrowRight size={15} /></button></form>}
        <ProjectList projects={projects} selectedId={projectId} onSelect={setProject} onDelete={setProjectToDelete} />
        {selectedProject && <><div className="sidebar-section-header runs-header"><span>Lượt chạy gần đây</span></div><div className="run-list">{runs.map((item) => <button key={item.id} className={`run-item ${runId === item.id ? 'selected' : ''}`} onClick={() => setRun(item.id)}><span className={`run-dot ${statusClass(item.status)}`} /><span className="run-item-name">{item.prompt}</span><small>{statusNames[item.status]}</small></button>)}{!runs.length && <p className="sidebar-empty">Chưa có lượt chạy.</p>}</div></>}
        <div className="sidebar-footer"><div className="user-avatar">L</div><span><strong>Local user</strong><small>API M4 · WSL2</small></span><button aria-label="Đăng xuất" title="Đăng xuất" onClick={() => setToken('')}><LogOut size={17} /></button></div>
      </aside>

      <main className="main-area">
        <header className="topbar"><div className="breadcrumbs"><span>Dự án</span><ChevronRight size={14} /><strong>{selectedProject?.name || 'Chưa chọn dự án'}</strong>{run && <><ChevronRight size={14} /><span className="run-short">{run.id.slice(0, 8)}</span></>}</div><div className="topbar-right"><span className="api-online"><span /> API kết nối</span><button className="icon-button" title="Yêu cầu phê duyệt" aria-label="Yêu cầu phê duyệt" onClick={() => setShowApproval(true)}><Bell size={18} />{pendingApprovals.length > 0 && <i>{pendingApprovals.length}</i>}</button><div className="header-avatar">L</div></div></header>
        <div className="mobile-switcher"><select aria-label="Chọn dự án" value={projectId || ''} onChange={(event) => setProject(event.target.value || null)}><option value="">Chọn dự án</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select aria-label="Chọn lượt chạy" value={runId || ''} onChange={(event) => setRun(event.target.value || null)}><option value="">Chọn lượt chạy</option>{runs.map((item) => <option key={item.id} value={item.id}>{item.prompt}</option>)}</select><button aria-label="Tạo dự án" onClick={() => setShowProjectForm(!showProjectForm)}><Plus size={17} /></button>{selectedProject && <button aria-label={`Xóa dự án ${selectedProject.name}`} onClick={() => setProjectToDelete(selectedProject)}><Trash2 size={17} /></button>}</div>
        {showProjectForm && <form className="mobile-project-form" onSubmit={createProject}><input aria-label="Tên dự án mới trên điện thoại" value={newProject} onChange={(event) => setNewProject(event.target.value)} placeholder="Tên dự án mới" /><button className="primary-button" type="submit" disabled={busy === 'project'}>Tạo</button></form>}
        <div className="page-content">
          {error && <div className="banner-error" role="alert">{error}<button onClick={() => setError('')} aria-label="Đóng thông báo"><X size={16} /></button></div>}
          <div className="page-heading"><div><span className="eyebrow">PROJECT WORKSPACE</span><h1>{selectedProject?.name || 'Bắt đầu dự án mới'}</h1><p>Theo dõi từng task, file và kết quả kiểm thử từ API M4.</p></div>{run && <div className={`run-status-pill ${statusClass(run.status)}`}><span className="pulse-dot" />{run.control_request === 'cancel' ? 'Đang hủy…' : run.control_request === 'pause' ? 'Đang tạm dừng…' : statusNames[run.status] || run.status}</div>}</div>

          <CodexConnection token={token} />
          <RoleSettings token={token} />
          <section className="composer panel"><div className="composer-icon"><Bot size={22} /></div><form onSubmit={createRun}><label htmlFor="run-prompt">Bạn muốn hệ thống thực hiện điều gì?</label><div className="composer-row"><textarea id="run-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Mô tả yêu cầu: tạo ứng dụng, nghiên cứu, viết báo cáo…" rows={2} disabled={!projectId} /><button className="primary-button" type="submit" disabled={!projectId || !prompt.trim() || busy === 'run' || !codexAccount.data?.connected}>{busy === 'run' ? 'Đang tạo…' : 'Bắt đầu chạy'} <Send size={16} /></button></div><div className="reference-picker"><label htmlFor="run-references"><Paperclip size={15} /> Thêm tài liệu tham chiếu</label><input id="run-references" type="file" aria-label="Chọn tài liệu tham chiếu" accept=".pdf,.docx,.txt,.md,.csv,.json" multiple disabled={!projectId || busy === 'run'} onChange={(event) => { addReferenceFiles(event.target.files); event.target.value = '' }} /><span>PDF, DOCX, TXT, MD, CSV, JSON · tối đa 3 tệp, 2 MB/tệp</span></div><div className="reference-picker"><label htmlFor="run-source"><FolderPlus size={15} /> Thêm thư mục source để tham chiếu</label><input id="run-source" type="file" aria-label="Chọn thư mục source tham chiếu" multiple {...{ webkitdirectory: '' }} disabled={!projectId || busy === 'run'} onChange={(event) => { addSourceFolder(event.target.files); event.target.value = '' }} /><span>Đọc file mã nguồn để tạo project mới · tối đa 40 file, 2 MB tổng cộng</span></div>{sourceFiles.length > 0 && <div className="reference-chips"><span>{sourcePath(sourceFiles[0]).split('/')[0]}/ · {sourceFiles.length} file<button type="button" aria-label="Bỏ thư mục source tham chiếu" onClick={() => setSourceFiles([])}><X size={13} /></button></span></div>}{referenceFiles.length > 0 && <div className="reference-chips">{referenceFiles.map((file, index) => <span key={`${file.name}-${index}`}>{file.name}<button type="button" aria-label={`Bỏ tài liệu ${file.name}`} onClick={() => setReferenceFiles((current) => current.filter((_, i) => i !== index))}><X size={13} /></button></span>)}</div>}<small>Coordinator tự chọn agent phù hợp. Tài liệu được gửi đến từng agent; QA đối chiếu với kết quả trước khi bàn giao. Xem kết quả trong tab Preview.</small></form></section>

          <div className="metrics-grid"><div className="metric-card"><span><Activity size={16} /> Tiến độ</span><strong>{tasks.length ? `${progress}%` : '—'}</strong><small>{completed}/{tasks.length} task hoàn thành</small></div><div className="metric-card"><span><WorkflowIcon size={16} /> Tasks</span><strong>{tasks.length || '—'}</strong><small>{tasks.length ? 'Trong DAG hiện tại' : 'Chờ lượt chạy'}</small></div><div className="metric-card"><span><Clock3 size={16} /> Bắt đầu</span><strong className="metric-date">{run ? new Date(run.created_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : '—'}</strong><small>{run ? new Date(run.created_at).toLocaleDateString('vi-VN') : 'Chưa có dữ liệu'}</small></div><div className="metric-card"><span><ShieldCheck size={16} /> Kiểm thử</span><strong className="metric-date">{reportQuery.data?.integration?.exit_code === 0 ? 'Đạt' : run?.status === 'COMPLETED' ? 'Hoàn tất' : '—'}</strong><small>{reportQuery.data?.integration?.stdout ? String(reportQuery.data.integration.stdout).trim().split('\n').at(-1) : 'Chờ QA'}</small></div></div>

          {run && <div className="run-toolbar"><div className="run-toolbar-id"><span className="label">RUN ID</span><code>{run.id}</code></div><div className="run-toolbar-actions">{(run.status === 'RUNNING' || run.status === 'CREATED') && !run.control_request && <button onClick={() => control('pause')} disabled={Boolean(busy)}><Pause size={15} /> Tạm dừng</button>}{run.status === 'PAUSED' && <button onClick={() => control('resume')} disabled={Boolean(busy)}><Play size={15} /> Tiếp tục</button>}{['RUNNING', 'CREATED', 'PAUSED'].includes(run.status) && <button className="danger-button" onClick={() => control('cancel')} disabled={Boolean(busy) || run.control_request === 'cancel'}><Square size={14} /> Hủy</button>}<button onClick={download} disabled={(reportQuery.data?.target === 'research_report' ? run.status !== 'COMPLETED' || !files.some((file) => file.path === 'REPORT.md') : !artifactsQuery.data?.some((item) => item.path === 'source.zip')) || Boolean(busy)}><Download size={15} /> {reportQuery.data?.target === 'research_report' ? 'Tải báo cáo' : 'Tải mã nguồn'}</button></div></div>}

          <div className="dashboard-grid"><section className="workflow-panel panel"><div className="panel-heading"><div><span className="panel-eyebrow">ORCHESTRATION</span><h2><WorkflowIcon size={18} /> Workflow</h2></div><span className="panel-tag">DAG · {tasks.length} task</span></div><Workflow tasks={tasks} selectedTaskId={taskId} onSelect={setTask} /></section><aside className="progress-panel panel"><div className="panel-heading"><div><span className="panel-eyebrow">LIVE STATUS</span><h2><Activity size={18} /> Tiến trình</h2></div></div><div className="progress-summary"><div><span>Tổng tiến độ</span><strong>{progress}%</strong></div><div className="progress-track"><span style={{ width: `${progress}%` }} /></div></div><AgentActivity run={run} tasks={tasks} events={events} selectedTask={selectedTask} taskEvents={taskActivityQuery.data || []} historyLoading={taskActivityQuery.isPending} historyError={taskActivityQuery.isError} /><div className="task-timeline">{tasks.map((task: Task) => <button key={task.id} className={`timeline-item ${taskId === task.id ? 'selected' : ''}`} onClick={() => setTask(task.id)}><span className={`timeline-marker ${statusClass(task.status)}`}>{task.status === 'COMPLETED' && <Check size={11} />}</span><span><strong>{task.title}</strong><small>{statusNames[task.status] || task.status} · {roleNames[task.agent_role] || task.agent_role}</small></span></button>)}{!tasks.length && <p className="empty-note">Các bước thực hiện sẽ xuất hiện tại đây.</p>}</div>{selectedTask && <div className="agent-inspector"><span className="panel-eyebrow">AGENT INSPECTOR</span><strong>{roleNames[selectedTask.agent_role] || selectedTask.agent_role}</strong><p>{selectedTask.title}</p><small>{selectedTask.model ? `Model: ${selectedTask.model} · ` : ''}Phụ thuộc: {selectedTask.depends_on.join(', ') || 'Không có'}</small></div>}</aside></div>

          {run && <div className="bottom-grid"><section className="activity-panel panel"><div className="panel-heading"><div><span className="panel-eyebrow">ACTIVITY</span><h2><Bot size={18} /> Yêu cầu & sự kiện</h2></div><span className="panel-tag">{events.length} sự kiện</span></div><div className="prompt-message"><div className="message-avatar">Y</div><p>{run.prompt}</p></div><RunReferences references={referencesQuery.data || []} checks={reportQuery.data?.reference_checks || []} events={events} />{run.status === 'BLOCKED' && reportQuery.data?.reason && <p className="reference-failure" role="alert">{reportQuery.data.reason}</p>}<div className="recent-events">{latestEvents.map((event) => <div className="recent-event" key={event.event_id}><span className="event-bullet" /><span>{recentEvent(event)}</span><time>{new Date(event.timestamp).toLocaleTimeString('vi-VN')}</time></div>)}</div></section><Workspace token={token} runId={run.id} files={files} report={reportQuery.data} events={events} preview={run.engine?.startsWith('codex')} webApp={run.engine === 'codex_web'} /></div>}
          {!run && <div className="new-workspace-hint"><FolderPlus size={26} /><strong>{selectedProject ? 'Tạo lượt chạy đầu tiên' : 'Tạo dự án đầu tiên'}</strong><p>{selectedProject ? 'Nhập yêu cầu ở phía trên để bắt đầu workflow.' : 'Bấm dấu + ở thanh bên để tạo không gian làm việc.'}</p></div>}
        </div>
      </main>

      {projectToDelete && <div className="modal-backdrop" onClick={() => setProjectToDelete(null)}><div className="approval-modal delete-project-modal" role="dialog" aria-modal="true" aria-label="Xóa dự án" onClick={(event) => event.stopPropagation()}><div className="modal-heading"><h2>Xóa dự án</h2><button aria-label="Đóng" onClick={() => setProjectToDelete(null)}><X size={18} /></button></div><p>Bạn có chắc muốn xóa <strong>{projectToDelete.name}</strong>?</p><p>Toàn bộ lượt chạy, log và mã nguồn đã tạo của dự án này sẽ bị xóa. Hãy hủy các lượt đang chạy trước.</p><div className="delete-project-actions"><button onClick={() => setProjectToDelete(null)} disabled={busy === 'delete-project'}>Giữ lại</button><button className="danger-button" onClick={deleteProject} disabled={busy === 'delete-project'}><Trash2 size={15} /> {busy === 'delete-project' ? 'Đang xóa…' : 'Xóa dự án'}</button></div></div></div>}
      {showApproval && <div className="modal-backdrop" onClick={() => setShowApproval(false)}><div className="approval-modal" role="dialog" aria-modal="true" aria-label="Yêu cầu phê duyệt" onClick={(event) => event.stopPropagation()}><div className="modal-heading"><h2>Yêu cầu phê duyệt</h2><button aria-label="Đóng" onClick={() => setShowApproval(false)}><X size={18} /></button></div>{pendingApprovals.length ? pendingApprovals.map((approval) => <div key={approval.id} className="approval-item"><strong>{approval.action}</strong><pre>{JSON.stringify(approval.payload, null, 2)}</pre><div><button disabled={busy === 'approval'} onClick={() => decide(approval.id, 'reject')}>Từ chối</button><button className="primary-button" disabled={busy === 'approval'} onClick={() => decide(approval.id, 'approve')}><CircleCheck size={15} /> Phê duyệt</button></div></div>) : <p className="empty-note">Hiện không có yêu cầu đang chờ.</p>}</div></div>}
    </div>
  )
}

export default App
