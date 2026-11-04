import { memo, useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type NodeProps,
} from '@xyflow/react'
import { Braces, Check, Code2, FlaskConical, LoaderCircle, Monitor, X, Search, DraftingCompass, Palette, FileText, PackageCheck, Network } from 'lucide-react'
import { buildFlow, type TaskNode } from '../workflow'
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

const TaskCard = memo(function TaskCard({ data, selected }: NodeProps<TaskNode>) {
  const { task } = data
  const Icon = roleIcons[task.agent_role as keyof typeof roleIcons] || Braces
  return (
    <div className={`flow-card role-${task.agent_role} state-${task.status.toLowerCase()} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Top} className="flow-handle" />
      <div className="flow-card-top">
        <span className="agent-icon"><Icon size={20} /></span>
        <span className="flow-task-id">{task.id}</span>
        <span className="flow-card-state">
          {task.status === 'COMPLETED' ? <Check size={14} /> : task.status === 'RUNNING' ? <LoaderCircle size={14} className="spin" /> : task.status === 'FAILED' || task.status === 'CANCELLED' ? <X size={14} /> : <span className="state-dot" />}
        </span>
      </div>
      <strong>{roleNames[task.agent_role] || task.agent_role}</strong>
      <small>{task.title}</small>
      {(task.duration_ms != null || (task.input_tokens || 0) + (task.output_tokens || 0) > 0) && <div className="flow-card-metrics">{task.duration_ms != null && <span>{(task.duration_ms / 1000).toFixed(1)}s</span>}{(task.input_tokens || 0) + (task.output_tokens || 0) > 0 && <span>{(task.input_tokens || 0) + (task.output_tokens || 0)} tokens</span>}</div>}
      <Handle type="source" position={Position.Bottom} className="flow-handle" />
    </div>
  )
})

const nodeTypes = { task: TaskCard }

export function Workflow({ tasks, selectedTaskId, onSelect }: { tasks: Task[]; selectedTaskId: string | null; onSelect: (id: string) => void }) {
  const { nodes, edges } = useMemo(() => buildFlow(tasks), [tasks])
  if (!tasks.length) {
    return <div className="workflow-empty"><Braces size={30} /><strong>Chưa có workflow</strong><span>Tạo một lượt chạy để xem các task và quan hệ phụ thuộc.</span></div>
  }
  return (
    <div className="workflow-canvas" aria-label="Sơ đồ công việc">
      <ReactFlow
        nodes={nodes.map((node) => ({ ...node, selected: node.id === selectedTaskId }))}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.27 }}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelect(node.id)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="#293452" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
