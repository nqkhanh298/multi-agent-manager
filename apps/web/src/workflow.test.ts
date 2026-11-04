import { describe, expect, it } from 'vitest'
import { buildFlow } from './workflow'
import type { Task } from './types'

const tasks: Task[] = [
  { id: 'T1', title: 'Backend', agent_role: 'backend_dev', status: 'COMPLETED', depends_on: [], workspace_ref: null },
  { id: 'T2', title: 'Frontend', agent_role: 'frontend_dev', status: 'RUNNING', depends_on: [], workspace_ref: null },
  { id: 'T3', title: 'QA', agent_role: 'qa', status: 'PENDING', depends_on: ['T1', 'T2'], workspace_ref: null },
]

describe('workflow graph', () => {
  it('places independent tasks in one column and QA to their right', () => {
    const { nodes, edges, width } = buildFlow(tasks)
    expect(nodes.find((node) => node.id === 'T1')?.position.x).toBe(60)
    expect(nodes.find((node) => node.id === 'T2')?.position.x).toBe(60)
    expect(nodes.find((node) => node.id === 'T1')?.position.y).not.toBe(nodes.find((node) => node.id === 'T2')?.position.y)
    expect(nodes.find((node) => node.id === 'T3')?.position.x).toBeGreaterThan(60)
    expect(width).toBeGreaterThan(600)
    expect(edges.map((edge) => `${edge.source}->${edge.target}`)).toEqual(['T1->T3', 'T2->T3'])
    expect(edges.every((edge) => edge.type === 'smoothstep')).toBe(true)
  })
})
