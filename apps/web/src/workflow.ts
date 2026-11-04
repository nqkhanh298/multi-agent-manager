import { MarkerType, type Edge, type Node } from '@xyflow/react'
import type { Task } from './types'

export type TaskNode = Node<{ task: Task }, 'task'>

export const CARD_WIDTH = 244
const CARD_HEIGHT = 166
const COLUMN_GAP = 82
const ROW_GAP = 34
const MARGIN = 60

const roleColors: Record<string, string> = {
  coordinator: '#8e83ff', researcher: '#46d5dc', architect: '#b789ff',
  designer: '#f281c6', developer: '#5f9eff', backend_dev: '#5f9eff',
  frontend_dev: '#6eb9ff', qa: '#f1bd61', writer: '#6bd7a8', release: '#8adf79',
}

export function buildFlow(tasks: Task[]): { nodes: TaskNode[]; edges: Edge[]; width: number; height: number } {
  const byId = new Map(tasks.map((task) => [task.id, task]))
  const depthCache = new Map<string, number>()
  function depth(id: string): number {
    if (depthCache.has(id)) return depthCache.get(id)!
    const task = byId.get(id)
    if (!task || task.depends_on.length === 0) return 0
    const level = 1 + Math.max(...task.depends_on.map(depth))
    depthCache.set(id, level)
    return level
  }
  const groups = new Map<number, Task[]>()
  for (const task of tasks) {
    const level = depth(task.id)
    groups.set(level, [...(groups.get(level) || []), task])
  }
  const levels = [...groups.keys()]
  const maxLevel = Math.max(0, ...levels)
  const maxRows = Math.max(1, ...[...groups.values()].map((group) => group.length))
  const width = MARGIN * 2 + (maxLevel + 1) * CARD_WIDTH + maxLevel * COLUMN_GAP
  const height = Math.max(300, 80 + maxRows * CARD_HEIGHT + (maxRows - 1) * ROW_GAP)
  const nodes: TaskNode[] = []
  for (const [level, group] of groups) {
    const groupHeight = group.length * CARD_HEIGHT + (group.length - 1) * ROW_GAP
    group.forEach((task, index) => {
      nodes.push({
        id: task.id,
        type: 'task',
        data: { task },
        position: {
          x: MARGIN + level * (CARD_WIDTH + COLUMN_GAP),
          y: (height - groupHeight) / 2 + index * (CARD_HEIGHT + ROW_GAP),
        },
      })
    })
  }
  const edges: Edge[] = tasks.flatMap((task) =>
    task.depends_on.map((parent) => {
      const color = task.status === 'RUNNING' ? roleColors[task.agent_role] || '#8e83ff'
        : task.status === 'COMPLETED' ? '#40d795' : '#627193'
      return {
        id: `${parent}-${task.id}`,
        source: parent,
        target: task.id,
        type: 'smoothstep',
        animated: task.status === 'RUNNING',
        className: task.status === 'RUNNING' ? 'flow-edge-active' : '',
        style: { stroke: color, strokeWidth: task.status === 'RUNNING' ? 2.8 : 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color },
      }
    }),
  )
  return { nodes, edges, width, height }
}
