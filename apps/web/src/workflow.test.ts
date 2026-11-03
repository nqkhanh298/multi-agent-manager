import { describe, expect, it } from 'vitest'
import { buildFlow } from './workflow'
import type { Task } from './types'

const tasks: Task[] = [
  { id: 'T1', title: 'Backend', agent_role: 'backend_dev', status: 'COMPLETED', depends_on: [], workspace_ref: null },
  { id: 'T2', title: 'Frontend', agent_role: 'frontend_dev', status: 'RUNNING', depends_on: [], workspace_ref: null },
  { id: 'T3', title: 'QA', agent_role: 'qa', status: 'PENDING', depends_on: ['T1', 'T2'], workspace_ref: null },
]

describe('workflow graph', () => {
  it('places independent tasks in one row and QA after both dependencies', () => {
    const { nodes, edges } = buildFlow(tasks)
    expect(nodes.find((node) => node.id === 'T1')?.position.y).toBe(0)
    expect(nodes.find((node) => node.id === 'T2')?.position.y).toBe(0)
    expect(nodes.find((node) => node.id === 'T3')?.position.y).toBe(190)
    expect(edges.map((edge) => `${edge.source}->${edge.target}`)).toEqual(['T1->T3', 'T2->T3'])
  })
})
