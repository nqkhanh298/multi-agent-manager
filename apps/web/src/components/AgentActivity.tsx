import type { Run, RunEvent, Task } from '../types'

const roles: Record<string, string> = {
  coordinator: 'Coordinator', researcher: 'Researcher', architect: 'Architect',
  designer: 'Designer', developer: 'Developer', qa: 'QA', writer: 'Writer', release: 'Release',
}

const phases: Record<string, string> = {
  connecting: 'Kết nối', thinking: 'Đang phân tích', writing: 'Đang soạn',
  source: 'Nguồn dữ liệu', tool: 'Công cụ', tool_result: 'Kết quả công cụ',
  summary: 'Tóm tắt suy luận', output: 'Đầu ra', sandbox: 'Docker',
  preparing: 'Chuẩn bị', completed: 'Hoàn thành', stopping: 'Đang dừng',
}

export function AgentActivity({ run, tasks, events, selectedTask, taskEvents, historyLoading, historyError }: {
  run?: Run
  tasks: Task[]
  events: RunEvent[]
  selectedTask?: Task
  taskEvents: RunEvent[]
  historyLoading?: boolean
  historyError?: boolean
}) {
  if (!run) return null
  const active = tasks.find((task) => task.status === 'RUNNING')
  const current = [...events].reverse().find((event) => event.type === 'task.activity' && event.payload.task_id === active?.id)
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
    {selectedTask && <div className="task-activity-section">
      <div className="task-activity-heading"><b>LỊCH SỬ BLOCK · {roles[selectedTask.agent_role] || selectedTask.agent_role}</b><span>{taskEvents.length} bước</span></div>
      <div className="agent-activity-history" aria-label={`Lịch sử hoạt động của ${selectedTask.agent_role}`}>
        {taskEvents.length ? taskEvents.map((event) => <div key={event.event_id} className="task-activity-entry">
          <time>{new Date(event.timestamp).toLocaleTimeString('vi-VN')}</time>
          <span><b>{phases[String(event.payload.phase)] || String(event.payload.phase || 'Hoạt động')}</b><span>{String(event.payload.detail || '')}</span></span>
        </div>) : <p>{historyLoading ? 'Đang tải lịch sử block…' : historyError ? 'Không tải được lịch sử block.' : 'Block này chưa có hoạt động được ghi lại.'}</p>}
      </div>
    </div>}
  </div>
}
