import { expect, test, type Page } from '@playwright/test'

type MockRun = { id: string; project_id: string; prompt: string; status: string; version: number; created_at: string; updated_at: string; report_ref: null; engine?: 'demo' | 'codex'; control_request?: 'pause' | 'cancel' | null }

async function mockPlatform(page: Page) {
  const projects = [{ id: 'p1', name: 'Task Management', description: '', created_at: '2026-11-04T00:00:00Z' }]
  const runs: MockRun[] = [{ id: 'r1', project_id: 'p1', prompt: 'Xây ứng dụng quản lý công việc', status: 'RUNNING', version: 1, created_at: '2026-11-04T00:00:00Z', updated_at: '2026-11-04T00:00:00Z', report_ref: null }]
  const tasks = [
    { id: 'T1', title: 'Build task backend', agent_role: 'backend_dev', status: 'COMPLETED', depends_on: [], workspace_ref: null },
    { id: 'T2', title: 'Build task frontend', agent_role: 'frontend_dev', status: 'RUNNING', depends_on: [], workspace_ref: null },
    { id: 'T3', title: 'Run integration QA', agent_role: 'qa', status: 'PENDING', depends_on: ['T1', 'T2'], workspace_ref: null },
  ]
  const approvals = [{ id: 'a1', action: 'increase_budget', payload: { usd: 1 }, status: 'PENDING' }]
  const events = [{ event_id: 'e1', run_id: 'r1', sequence: 1, type: 'run.created', payload: {}, timestamp: '2026-11-04T00:00:00Z' }]
  const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })
  await page.addInitScript(() => sessionStorage.setItem('m5-api-token', 'test-token'))
  await page.routeWebSocket('**/ws/**', (socket) => socket.onMessage(() => {}))
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (path === '/api/codex/account') return route.fulfill(json({ connected: false, email: null, plan_type: null }))
    if (path === '/api/codex/login') return route.fulfill(json({ login_id: 'login-1', auth_url: null, verification_url: 'https://auth.openai.com/codex/device', user_code: 'ABCD-1234' }))
    if (path === '/api/projects' && method === 'GET') return route.fulfill(json(projects))
    if (path === '/api/projects' && method === 'POST') {
      const project = { id: `p${projects.length + 1}`, name: request.postDataJSON().name as string, description: '', created_at: new Date().toISOString() }
      projects.push(project)
      return route.fulfill(json(project, 201))
    }
    if (/^\/api\/projects\/[^/]+$/.test(path) && method === 'DELETE') {
      const id = path.split('/')[3]
      if (runs.some((run) => run.project_id === id && !['COMPLETED', 'FAILED', 'BLOCKED', 'CANCELLED'].includes(run.status))) {
        return route.fulfill(json({ detail: 'Hãy hủy hoặc hoàn tất các lượt chạy trước khi xóa dự án' }, 409))
      }
      const index = projects.findIndex((project) => project.id === id)
      if (index < 0) return route.fulfill(json({ detail: 'project not found' }, 404))
      projects.splice(index, 1)
      return route.fulfill(json({ deleted: true, removed_runs: runs.filter((run) => run.project_id === id).length, cleanup_failed: false }))
    }
    if (/^\/api\/projects\/[^/]+\/runs$/.test(path) && method === 'GET') return route.fulfill(json(runs.filter((run) => run.project_id === path.split('/')[3])))
    if (/^\/api\/projects\/[^/]+\/runs$/.test(path) && method === 'POST') {
      const run: MockRun = { id: `r${runs.length + 1}`, project_id: path.split('/')[3], prompt: request.postDataJSON().prompt as string, status: 'CREATED', version: 0, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), report_ref: null }
      runs.unshift(run)
      return route.fulfill(json(run, 202))
    }
    const id = path.split('/')[3]
    const run = runs.find((item) => item.id === id) || runs[0]
    if (/^\/api\/runs\/[^/]+$/.test(path)) return route.fulfill(json(run))
    if (path.endsWith('/tasks')) return route.fulfill(json(tasks))
    if (path.endsWith('/events')) return route.fulfill(json(events))
    if (path.endsWith('/files')) return route.fulfill(json([{ path: 'backend.py', size: 80 }, { path: 'App.jsx', size: 100 }] ))
    if (path.endsWith('/files/backend.py')) return route.fulfill(json({ path: 'backend.py', content: 'def create_task(title):\n    return {"title": title}\n' }))
    if (path.endsWith('/files/App.jsx')) return route.fulfill(json({ path: 'App.jsx', content: 'export default function App() { return <h1>Tasks</h1> }' }))
    if (path.endsWith('/diff')) return route.fulfill(json({ path: 'backend.py', diff: '--- a/backend.py\n+++ b/backend.py\n@@ -0,0 +1 @@\n+def create_task(title):' }))
    if (path.endsWith('/report')) return route.fulfill(json({ status: 'RUNNING', parallel_overlap_ms: 1000, tasks: [{ task_id: 'T1', status: 'COMPLETED', test_stdout: '2 passed', reason: '' }], merges: [], integration: { stdout: '4 passed', exit_code: 0 } }))
    if (path.endsWith('/artifacts')) return route.fulfill(json([{ id: 'z1', path: 'source.zip', sha256: 'abc', size: 120 }]))
    if (path.endsWith('/approvals')) return route.fulfill(json(approvals))
    if (path.endsWith('/download')) return route.fulfill({ status: 200, headers: { 'Content-Type': 'application/zip', 'Content-Disposition': 'attachment; filename="source.zip"' }, body: 'PK\u0003\u0004' })
    if (method === 'POST' && path.endsWith('/pause')) { run.status = 'PAUSED'; return route.fulfill(json(run)) }
    if (method === 'POST' && path.endsWith('/resume')) { run.status = 'CREATED'; return route.fulfill(json(run)) }
    if (method === 'POST' && path.endsWith('/cancel')) { if (run.engine === 'codex') run.control_request = 'cancel'; else run.status = 'CANCELLED'; return route.fulfill(json(run)) }
    if (method === 'POST' && path.includes('/approvals/')) { approvals[0].status = 'APPROVED'; return route.fulfill(json({ id: 'a1', status: 'APPROVED' })) }
    return route.fulfill(json([]))
  })
  return { runs, tasks, events }
}

test('shows live agent activity and a pending cancel request', async ({ page }) => {
  const state = await mockPlatform(page)
  state.runs[0].engine = 'codex'
  state.tasks[1].agent_role = 'coordinator'
  state.tasks[1].title = 'Phân tích yêu cầu'
  state.events.push({ event_id: 'e2', run_id: 'r1', sequence: 2, type: 'task.activity', payload: { task_id: 'T2', role: 'coordinator', phase: 'thinking', detail: 'Codex đang phân tích yêu cầu' }, timestamp: '2026-11-04T00:00:01Z' })
  await page.goto('/')
  await expect(page.getByText('Codex đang phân tích yêu cầu').first()).toBeVisible()
  await page.getByRole('button', { name: 'Hủy', exact: true }).click()
  await expect(page.getByText('Đang hủy lượt chạy…')).toBeVisible()
})

test('deletes a finished project after confirmation and blocks active work', async ({ page }) => {
  const state = await mockPlatform(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Xóa dự án Task Management' }).click()
  await expect(page.getByRole('dialog', { name: 'Xóa dự án' })).toBeVisible()
  await page.getByRole('button', { name: 'Xóa dự án', exact: true }).click()
  await expect(page.locator('.banner-error')).toContainText('Hãy hủy hoặc hoàn tất')
  state.runs[0].status = 'CANCELLED'
  await page.getByRole('button', { name: 'Xóa dự án', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Xóa dự án' })).toBeHidden()
  await expect(page.getByText('Tạo dự án đầu tiên để bắt đầu.')).toBeVisible()
})

test('shows task graph, progress, code and test output from API data', async ({ page }) => {
  await mockPlatform(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Task Management' })).toBeVisible()
  await expect(page.getByText('Backend Dev').first()).toBeVisible()
  await expect(page.getByText('Frontend Dev').first()).toBeVisible()
  await expect(page.getByText('33%').first()).toBeVisible()
  await page.getByRole('tab', { name: /Diff/ }).click()
  await expect(page.locator('.diff-add')).toContainText('def create_task')
  await page.getByRole('tab', { name: /Tests/ }).click()
  await expect(page.locator('.terminal-output')).toContainText('4 passed')
  await page.getByRole('tab', { name: /Events/ }).click()
  await expect(page.locator('.event-log .event-type')).toContainText('run.created')
})

test('keeps eight specialist stages readable in a horizontal workflow', async ({ page }) => {
  const state = await mockPlatform(page)
  const roles = ['coordinator', 'researcher', 'architect', 'designer', 'developer', 'qa', 'writer', 'release']
  state.tasks.splice(0, state.tasks.length, ...roles.map((role, index) => ({
    id: `T${index + 1}`, title: `${role} task`, agent_role: role,
    status: index < 3 ? 'COMPLETED' : index === 3 ? 'RUNNING' : 'PENDING',
    depends_on: index ? [`T${index}`] : [], workspace_ref: null,
  })))
  await page.goto('/')
  await expect(page.locator('.react-flow__node')).toHaveCount(8)
  await expect(page.locator('.flow-card.role-designer .flow-card-meta')).toContainText('THIẾT KẾ')
  await expect(page.locator('.flow-card.role-qa .flow-card-meta')).toContainText('KIỂM THỬ')
  await expect(page.locator('.flow-card.role-release .flow-card-meta')).toContainText('BÀN GIAO')
  const viewport = page.locator('.workflow-canvas')
  expect(await viewport.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
  await viewport.evaluate((element) => { element.scrollLeft = 0 })
  await page.getByRole('button', { name: 'Xem bước tiếp' }).click()
  await expect.poll(() => viewport.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('button', { name: 'Xem bước tiếp' })).toBeVisible()
  expect(await viewport.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
})

test('creates a run and controls its lifecycle', async ({ page }) => {
  await mockPlatform(page)
  await page.goto('/')
  await page.getByRole('radio', { name: /Demo Task Manager/ }).check()
  await page.getByLabel('Bạn muốn hệ thống xây gì?').fill('Ứng dụng mới')
  await page.getByRole('button', { name: /Bắt đầu chạy/ }).click()
  await expect(page.getByText('Ứng dụng mới').first()).toBeVisible()
  await page.getByRole('button', { name: /Tạm dừng/ }).click()
  await expect(page.getByText('Tạm dừng', { exact: true }).last()).toBeVisible()
  await page.getByRole('button', { name: /Tiếp tục/ }).click()
  await page.getByRole('button', { name: /Hủy/ }).click()
  await expect(page.getByText('Đã hủy').first()).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /Tải mã nguồn/ }).click()
  expect((await download).suggestedFilename()).toContain('source.zip')
})

test('offers ChatGPT connection before a real Codex run', async ({ page }) => {
  await mockPlatform(page)
  await page.goto('/')
  await expect(page.getByRole('button', { name: /Bắt đầu chạy/ })).toBeDisabled()
  await page.getByRole('button', { name: 'Dùng mã thiết bị' }).click()
  await expect(page.getByText('ABCD-1234')).toBeVisible()
})

test('requires a deliberate approval decision', async ({ page }) => {
  await mockPlatform(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Yêu cầu phê duyệt' }).click()
  await expect(page.getByRole('dialog', { name: 'Yêu cầu phê duyệt' })).toBeVisible()
  await expect(page.getByText('increase_budget')).toBeVisible()
  await page.getByRole('button', { name: 'Phê duyệt', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Yêu cầu phê duyệt' })).toBeHidden()
})

test('keeps project creation available on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockPlatform(page)
  await page.goto('/')
  await expect(page.getByRole('combobox', { name: 'Chọn dự án' })).toBeVisible()
  await page.getByRole('button', { name: 'Tạo dự án' }).click()
  await page.getByRole('textbox', { name: 'Tên dự án mới trên điện thoại' }).fill('Mobile app')
  await page.getByRole('button', { name: 'Tạo', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Chọn dự án' })).toHaveValue('p2')
})
