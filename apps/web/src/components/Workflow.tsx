import { memo, useEffect, useMemo, useRef } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type NodeProps,
} from '@xyflow/react'
import { Braces, Check, ChevronLeft, ChevronRight, Code2, Cpu, DraftingCompass, FileText, FlaskConical, LoaderCircle, Monitor, Network, PackageCheck, Palette, Search, X } from 'lucide-react'
import { buildFlow, CARD_WIDTH, type TaskNode } from '../workflow'
import type { Task } from '../types'

const roleIcons = {
  coordinator: Network,
  researcher: Search,
  architect: DraftingCompass,
  designer: Palette,
  developer: Code2,
  backend_dev: Code2,
  frontend_dev: Monitor,
  qa: FlaskConical,
  writer: FileText,
  release: PackageCheck,
}

const roleNames: Record<string, string> = {
  coordinator: 'Coordinator',
  researcher: 'Researcher',
  architect: 'Architect',
  designer: 'Designer',
  developer: 'Developer',
  backend_dev: 'Backend Dev',
  frontend_dev: 'Frontend Dev',
  qa: 'QA',
  writer: 'Writer',
  release: 'Release',
}

const roleStages: Record<string, string> = {
  coordinator: 'ĐIỀU PHỐI', researcher: 'NGHIÊN CỨU', architect: 'KIẾN TRÚC',
  designer: 'THIẾT KẾ', developer: 'PHÁT TRIỂN', backend_dev: 'BACKEND',
  frontend_dev: 'FRONTEND', qa: 'KIỂM THỬ', writer: 'TÀI LIỆU', release: 'BÀN GIAO',
}

const statusLabels: Record<string, string> = {
  PENDING: 'Chờ', READY: 'Sẵn sàng', RUNNING: 'Đang chạy', VERIFYING: 'Kiểm tra',
  COMPLETED: 'Xong', FAILED: 'Lỗi', BLOCKED: 'Bị chặn', CANCELLED: 'Đã hủy',
}

const TaskCard = memo(function TaskCard({ data, selected }: NodeProps<TaskNode>) {
  const { task } = data
  const Icon = roleIcons[task.agent_role as keyof typeof roleIcons] || Braces
  const modelLabel = task.model_source === 'runtime' ? 'MODEL ĐANG DÙNG'
    : task.model_source === 'configured' ? 'MODEL ĐÃ CHỌN'
      : task.model_source?.startsWith('default') ? 'MODEL MẶC ĐỊNH' : 'MODEL'
  const modelName = task.model || (task.model_source === 'default_pending' ? 'Chờ xác định khi chạy'
    : task.model_source === 'default_unknown' ? 'Chưa ghi nhận' : 'Chưa có dữ liệu')
  const modelProvider = task.model_source && task.model_source !== 'unknown' ? 'CODEX · ' : ''
  return (
    <div className={`flow-card role-${task.agent_role} state-${task.status.toLowerCase()} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="flow-card-top">
        <span className="agent-icon"><Icon size={20} /></span>
        <span className="flow-card-meta"><b>{roleStages[task.agent_role] || 'AGENT'}</b><span className="flow-task-id">{task.id}</span></span>
        <span className="flow-card-state">
          {task.status === 'COMPLETED' ? <Check size={14} /> : task.status === 'RUNNING' ? <LoaderCircle size={14} className="spin" /> : task.status === 'FAILED' || task.status === 'CANCELLED' ? <X size={14} /> : <span className="state-dot" />}
          {statusLabels[task.status] || task.status}
        </span>
      </div>
      <strong>{roleNames[task.agent_role] || task.agent_role}</strong>
      <small>{task.title}</small>
      <div className={`flow-card-model ${task.model_source === 'runtime' ? 'resolved' : ''}`} title={modelName}>
        <span><Cpu size={13} /> {modelProvider}{modelLabel}</span><b>{modelName}</b>
      </div>
      {(task.duration_ms != null || (task.input_tokens || 0) + (task.output_tokens || 0) > 0) && <div className="flow-card-metrics">{task.duration_ms != null && <span>{(task.duration_ms / 1000).toFixed(1)}s</span>}{(task.input_tokens || 0) + (task.output_tokens || 0) > 0 && <span>{(task.input_tokens || 0) + (task.output_tokens || 0)} tokens</span>}</div>}
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  )
})

const nodeTypes = { task: TaskCard }

export function Workflow({ tasks, selectedTaskId, onSelect }: { tasks: Task[]; selectedTaskId: string | null; onSelect: (id: string) => void }) {
  const { nodes, edges, width, height } = useMemo(() => buildFlow(tasks), [tasks])
  const viewport = useRef<HTMLDivElement>(null)
  const activeId = tasks.find((task) => task.status === 'RUNNING')?.id
  useEffect(() => {
    if (!activeId || !viewport.current) return
    const node = nodes.find((item) => item.id === activeId)
    if (node) viewport.current.scrollTo({ left: Math.max(0, node.position.x + CARD_WIDTH / 2 - viewport.current.clientWidth / 2), behavior: 'smooth' })
  }, [activeId, width])
  if (!tasks.length) {
    return <div className="workflow-empty"><Braces size={30} /><strong>Chưa có workflow</strong><span>Tạo một lượt chạy để xem các task và quan hệ phụ thuộc.</span></div>
  }
  return (
    <div className="workflow-shell">
      <div className="workflow-legend">
        <span className="legend-discovery">Nghiên cứu</span><span className="legend-design">Thiết kế</span><span className="legend-build">Phát triển</span><span className="legend-verify">Kiểm thử</span><span className="legend-deliver">Bàn giao</span>
        <div className="workflow-navigation"><small>Quy trình từ trái sang phải</small><button aria-label="Xem bước trước" onClick={() => viewport.current?.scrollBy({ left: -420, behavior: 'smooth' })}><ChevronLeft size={16} /></button><button aria-label="Xem bước tiếp" onClick={() => viewport.current?.scrollBy({ left: 420, behavior: 'smooth' })}><ChevronRight size={16} /></button></div>
      </div>
    <div className="workflow-canvas" aria-label="Sơ đồ công việc" ref={viewport} style={{ height }}>
      <div className="workflow-stage" style={{ minWidth: width, height }}>
      <ReactFlow
        nodes={nodes.map((node) => ({ ...node, selected: node.id === selectedTaskId }))}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.06, minZoom: 0.85, maxZoom: 1 }}
        nodesDraggable={false}
        nodesConnectable={false}
        panOnDrag={false}
        panOnScroll={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        onNodeClick={(_, node) => onSelect(node.id)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={22} size={1} color="#293452" />
        <Controls showInteractive={false} />
      </ReactFlow>
      </div>
    </div>
    </div>
  )
}
