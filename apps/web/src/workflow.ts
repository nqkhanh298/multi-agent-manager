import type { Edge, Node } from '@xyflow/react'
import type { Task } from './types'

export type TaskNode = Node<{ task: Task }, 'task'>

export function buildFlow(tasks: Task[]): { nodes: TaskNode[]; edges: Edge[] } {
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
  const nodes: TaskNode[] = []
  for (const [level, group] of groups) {
    group.forEach((task, index) => {
      const width = 270
      const gap = 40
      const total = group.length * width + (group.length - 1) * gap
      nodes.push({
        id: task.id,
        type: 'task',
        data: { task },
        position: { x: index * (width + gap) - total / 2 + width / 2, y: level * 190 },
      })
    })
  }
  const edges: Edge[] = tasks.flatMap((task) =>
    task.depends_on.map((parent) => ({
      id: `${parent}-${task.id}`,
      source: parent,
      target: task.id,
      animated: task.status === 'RUNNING',
      style: { stroke: task.status === 'COMPLETED' ? '#35d995' : '#64739d', strokeWidth: 2 },
    })),
  )
  return { nodes, edges }
}
