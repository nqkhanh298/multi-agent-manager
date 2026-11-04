import { lazy, Suspense, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileCode2, FileDiff, FileText, FolderTree, MonitorPlay, TerminalSquare, TestTube2 } from 'lucide-react'
import { api } from '../api'
import { useUI } from '../store'
import { WebPreview } from './WebPreview'
import { TerminalPreview } from './TerminalPreview'
import type { RunEvent, RunReport, SourceFile } from '../types'

const MonacoView = lazy(() => import('./MonacoView'))

function languageFor(path: string): string {
  if (path.endsWith('.py')) return 'python'
  if (path.endsWith('.jsx') || path.endsWith('.js')) return 'javascript'
  if (path.endsWith('.tsx') || path.endsWith('.ts')) return 'typescript'
  if (path.endsWith('.json')) return 'json'
  if (path.endsWith('.md')) return 'markdown'
  return 'plaintext'
}

function testOutput(report?: RunReport): string {
  if (!report) return 'Kết quả kiểm thử sẽ xuất hiện khi worker chạy.'
  const parts = report.tasks.flatMap((task) =>
    task.test_stdout ? [`$ ${task.task_id} · ${task.status}\n${task.test_stdout}`] : [],
  )
  if (report.integration?.stdout) parts.push(`$ Integration QA\n${report.integration.stdout}`)
  if (report.integration?.frontend_build) parts.push(`$ Frontend build\n${report.integration.frontend_build}`)
  return parts.join('\n') || 'Chưa có kết quả kiểm thử.'
}

export function Workspace({ token, runId, files, report, events, preview = false, webApp = false }: { token: string; runId: string; files: SourceFile[]; report?: RunReport; events: RunEvent[]; preview?: boolean; webApp?: boolean }) {
  const filePath = useUI((state) => state.filePath)
  const setFile = useUI((state) => state.setFile)
  const tab = useUI((state) => state.workspaceTab)
  const setTab = useUI((state) => state.setWorkspaceTab)
  useEffect(() => {
    if (tab === 'preview' && !preview) setTab('code')
  }, [tab, preview, setTab])
  const fileQuery = useQuery({
    queryKey: ['file', runId, filePath],
    queryFn: () => api.file(token, runId, filePath!),
    enabled: Boolean(filePath),
    retry: false,
  })
  const diffQuery = useQuery({
    queryKey: ['diff', runId, filePath],
    queryFn: () => api.diff(token, runId, filePath!),
    enabled: Boolean(filePath) && tab === 'diff',
    retry: false,
  })

  useEffect(() => {
    if (files.length && !files.some((file) => file.path === filePath)) {
      setFile(files.find((file) => file.path === 'index.html')?.path || files.find((file) => file.path === 'backend.py')?.path || files[0].path)
    }
  }, [files, filePath, setFile])

  return (
    <section className={`workspace-panel panel ${tab === 'preview' && preview ? 'workspace-preview' : ''}`}>
      <div className="workspace-tabs" role="tablist" aria-label="Không gian làm việc">
        {preview && <button role="tab" aria-selected={tab === 'preview'} className={tab === 'preview' ? 'active' : ''} onClick={() => setTab('preview')}><MonitorPlay size={15} /> Preview</button>}
        <button role="tab" aria-selected={tab === 'code'} className={tab === 'code' ? 'active' : ''} onClick={() => setTab('code')}><FileCode2 size={15} /> Code</button>
        <button role="tab" aria-selected={tab === 'diff'} className={tab === 'diff' ? 'active' : ''} onClick={() => setTab('diff')}><FileDiff size={15} /> Diff</button>
        <button role="tab" aria-selected={tab === 'tests'} className={tab === 'tests' ? 'active' : ''} onClick={() => setTab('tests')}><TestTube2 size={15} /> Tests</button>
        <button role="tab" aria-selected={tab === 'logs'} className={tab === 'logs' ? 'active' : ''} onClick={() => setTab('logs')}><TerminalSquare size={15} /> Events <span className="tab-count">{events.length}</span></button>
      </div>
      {tab === 'preview' && preview && (report?.target === 'web' || webApp || (!report?.target && files.some((file) => file.path === 'index.html')) ? <WebPreview token={token} runId={runId} /> : report?.target === 'python_cli' || files.some((file) => file.path === 'app.py') ? <TerminalPreview token={token} runId={runId} /> : <div className="preview-placeholder">Hệ thống đang chọn cách tạo ứng dụng. Bản xem trước sẽ xuất hiện khi có mã nguồn.</div>)}
      {tab === 'code' && <div className="code-workspace">
        <aside className="file-explorer">
          <div className="subpanel-title"><FolderTree size={15} /> File Explorer <span>{files.length}</span></div>
          {files.length ? files.map((file) => <button key={file.path} className={`file-row ${filePath === file.path ? 'selected' : ''}`} onClick={() => setFile(file.path)} title={file.path}><FileText size={14} /> <span>{file.path}</span></button>) : <p className="empty-note">File sẽ xuất hiện sau khi các nhánh được merge.</p>}
        </aside>
        <div className="editor-area">
          <div className="editor-title"><FileCode2 size={14} /> {filePath || 'Chọn một file'} <span>Chỉ đọc</span></div>
          {filePath && fileQuery.data ? <Suspense fallback={<div className="editor-placeholder">Đang mở trình soạn thảo…</div>}><MonacoView path={filePath} content={fileQuery.data.content} language={languageFor(filePath)} /></Suspense> : <div className="editor-placeholder">{fileQuery.isLoading ? 'Đang tải file…' : fileQuery.isError ? 'Không đọc được file.' : 'Chọn file để xem mã nguồn.'}</div>}
        </div>
      </div>}
      {tab === 'diff' && <div className="diff-workspace"><div className="editor-title"><FileDiff size={14} /> {filePath || 'Chọn file trong tab Code để xem thay đổi'}</div><div className="diff-content">{diffQuery.isLoading ? <p className="empty-note">Đang tải diff…</p> : diffQuery.isError ? <p className="empty-note">Không đọc được diff.</p> : diffQuery.data?.diff ? diffQuery.data.diff.split('\n').map((line, index) => <div key={index} className={line.startsWith('+') && !line.startsWith('+++') ? 'diff-add' : line.startsWith('-') && !line.startsWith('---') ? 'diff-remove' : line.startsWith('@@') ? 'diff-hunk' : ''}>{line || ' '}</div>) : <p className="empty-note">Chưa có thay đổi Git cho file này hoặc lượt chạy chưa hoàn thành.</p>}</div></div>}
      {tab === 'tests' && <pre className="terminal-output">{testOutput(report)}</pre>}
      {tab === 'logs' && <div className="event-log">{events.length ? [...events].reverse().map((event) => <div className="event-row" key={event.event_id}><span className="event-seq">#{event.sequence}</span><span className="event-type">{event.type}</span><span className="event-payload">{JSON.stringify(event.payload)}</span><time>{new Date(event.timestamp).toLocaleTimeString('vi-VN')}</time></div>) : <div className="empty-note">Sự kiện sẽ xuất hiện khi bạn tạo lượt chạy.</div>}</div>}
    </section>
  )
}
