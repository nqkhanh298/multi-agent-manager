import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { RoleAssignment } from '../types'

const roles: [string, string][] = [
  ['coordinator', 'Điều phối'], ['researcher', 'Nghiên cứu'],
  ['architect', 'Kiến trúc'], ['designer', 'Thiết kế'],
  ['developer', 'Phát triển'], ['qa', 'Kiểm thử'],
  ['writer', 'Viết hướng dẫn'], ['release', 'Bàn giao'],
]

export function RoleSettings({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [assignments, setAssignments] = useState<Record<string, RoleAssignment>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const settings = useQuery({ queryKey: ['codex-roles'], queryFn: () => api.roleSettings(token) })
  const catalog = useQuery({ queryKey: ['codex-models'], queryFn: () => api.codexModels(token), enabled: open, retry: false })
  useEffect(() => { if (settings.data?.assignments) setAssignments(settings.data.assignments) }, [settings.data])

  async function saveRoles() {
    setBusy(true); setMessage('')
    try {
      await api.saveRoles(token, assignments)
      await queryClient.invalidateQueries({ queryKey: ['codex-roles'] })
      setMessage('Đã lưu model Codex cho từng vai trò. Lượt chạy mới sẽ dùng cấu hình này.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Không lưu được cấu hình')
    } finally { setBusy(false) }
  }

  return <section className="role-settings panel">
    <button type="button" className="role-settings-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>Model Codex theo vai trò <span>{open ? 'Ẩn' : 'Cấu hình'}</span></button>
    {open && <div className="role-settings-body">
      <p>Mỗi vai trò dùng skill và phiên Codex riêng. Chọn model cho từng vai trò; để “Mặc định” nếu muốn dùng model của tài khoản Codex.</p>
      {catalog.isError && <p role="status">Không tải được danh sách model Codex. Kiểm tra kết nối ChatGPT rồi thử lại.</p>}
      <div className="role-assignment-list">{roles.map(([role, label]) => {
        const selected = assignments[role]?.model || ''
        const models = catalog.data?.models || []
        return <div className="role-assignment-row" key={role}>
          <strong>{label}</strong>
          <select aria-label={`Model cho ${label}`} value={selected} onChange={(event) => setAssignments((current) => ({ ...current, [role]: { provider: 'codex', model: event.target.value } }))}>
            <option value="">Mặc định tài khoản</option>
            {selected && !models.includes(selected) && <option value={selected}>{selected} (đã lưu)</option>}
            {models.map((model) => <option key={model} value={model}>{model}</option>)}
          </select>
        </div>
      })}</div>
      <button type="button" className="primary-button" disabled={busy || !settings.data} onClick={saveRoles}>{busy ? 'Đang lưu…' : 'Lưu model cho vai trò'}</button>
      {message && <p role="status">{message}</p>}
    </div>}
  </section>
}
