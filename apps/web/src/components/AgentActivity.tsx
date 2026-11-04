import type { Run, RunEvent, Task } from '../types'

const roles: Record<string, string> = {
  coordinator: 'Coordinator', researcher: 'Researcher', architect: 'Architect',
  designer: 'Designer', developer: 'Developer', qa: 'QA', writer: 'Writer', release: 'Release',
}

export function AgentActivity({ run, tasks, events }: { run?: Run; tasks: Task[]; events: RunEvent[] }) {
  if (!run) return null
  const active = tasks.find((task) => task.status === 'RUNNING')
  const history = events.filter((event) => event.type === 'task.activity').slice(-6).reverse()
  const current = history.find((event) => event.payload.task_id === active?.id)
  const selection = [...events].reverse().find((event) => event.type === 'run.target_activity')
  const stopping = run.control_request === 'cancel' ? 'Đang hủy lượt chạy…' :
    run.control_request === 'pause' ? 'Đang tạm dừng…' : null
  const detail = stopping || (!active && run.engine === 'codex_auto' && !events.some((event) => event.type === 'run.target_selected') && selection ? String(selection.payload.detail || '') : active && current ? String(current.payload.detail || '') :
    active ? 'Đang khởi động agent…' : run.status === 'PAUSED' ? 'Đã tạm dừng. Bấm Tiếp tục để chạy tiếp.' :
      run.status === 'CANCELLED' ? 'Lượt chạy đã được hủy.' :
        run.status === 'COMPLETED' ? 'Các agent đã hoàn thành.' : 'Chờ agent bắt đầu.')

  return <div className="agent-activity" aria-live="polite">
    <span className="panel-eyebrow">ĐANG LÀM GÌ</span>
    <strong>{active ? `${roles[active.agent_role] || active.agent_role} · ${active.title}` : stopping || 'Trạng thái hiện tại'}</strong>
    <p>{detail}</p>
    {stopping && <small>Worker đang ngắt phiên Codex hoặc Docker. Trạng thái sẽ cập nhật khi đã dừng hẳn.</small>}
    {history.length > 0 && <div className="agent-activity-history">
      {history.map((event) => <div key={event.event_id}>
        <time>{new Date(event.timestamp).toLocaleTimeString('vi-VN')}</time>
        <span><b>{roles[String(event.payload.role)] || String(event.payload.role)}</b> · {String(event.payload.detail || '')}</span>
      </div>)}
    </div>}
  </div>
}
