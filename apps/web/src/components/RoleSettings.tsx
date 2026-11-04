import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { AIProvider, RoleAssignment } from '../types'

const roles: [string, string][] = [
  ['coordinator', 'Điều phối'], ['researcher', 'Nghiên cứu'],
  ['architect', 'Kiến trúc'], ['designer', 'Thiết kế'],
  ['developer', 'Phát triển'], ['qa', 'Kiểm thử'],
  ['writer', 'Viết hướng dẫn'], ['release', 'Bàn giao'],
]
const providers: AIProvider[] = ['codex', 'claude', 'gemini']

export function RoleSettings({ token }: { token: string }) {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['ai-roles'], queryFn: () => api.roleSettings(token) })
  const [open, setOpen] = useState(false)
  const [assignments, setAssignments] = useState<Record<string, RoleAssignment>>({})
  const [keys, setKeys] = useState({ claude: '', gemini: '' })
  const [models, setModels] = useState<Record<string, string[]>>({})
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => { if (settings.data?.assignments) setAssignments(settings.data.assignments) }, [settings.data])

  async function loadModels(provider: AIProvider) {
    if (models[provider]) return
    try {
      const response = await api.providerModels(token, provider)
      setModels((current) => ({ ...current, [provider]: response.models }))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Không tải được danh sách model')
    }
  }

  async function saveKey(provider: 'claude' | 'gemini') {
    setBusy(provider); setMessage('')
    try {
      await api.saveProviderKey(token, provider, keys[provider])
      setKeys((current) => ({ ...current, [provider]: '' }))
      await client.invalidateQueries({ queryKey: ['ai-roles'] })
      await loadModels(provider)
      setMessage(`Đã kết nối ${provider}.`)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Không lưu được khóa') }
    finally { setBusy('') }
  }

  async function removeKey(provider: 'claude' | 'gemini') {
    setBusy(provider); setMessage('')
    try {
      await api.deleteProviderKey(token, provider)
      setModels((current) => ({ ...current, [provider]: [] }))
      await client.invalidateQueries({ queryKey: ['ai-roles'] })
      setMessage(`Đã ngắt ${provider}.`)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Không ngắt được khóa') }
    finally { setBusy('') }
  }

  async function saveRoles() {
    setBusy('roles'); setMessage('')
    try {
      await api.saveRoles(token, assignments)
      await client.invalidateQueries({ queryKey: ['ai-roles'] })
      setMessage('Đã lưu AI và model cho từng vai trò. Lượt chạy mới sẽ dùng cấu hình này.')
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Không lưu được cấu hình') }
    finally { setBusy('') }
  }

  return <section className="role-settings panel">
    <button type="button" className="role-settings-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>AI cho từng vai trò <span>{open ? 'Ẩn' : 'Cấu hình'}</span></button>
    {open && <div className="role-settings-body">
      <p>Mỗi vai trò có phiên và skill riêng. Chọn nhà cung cấp cùng model; lượt chạy mới sẽ dùng đúng cấu hình đã lưu.</p>
      <div className="provider-keys">{(['claude', 'gemini'] as const).map((provider) => <div key={provider} className="provider-key-row">
        <strong>{provider === 'claude' ? 'Claude' : 'Gemini'} · {settings.data?.keys[provider] ? 'Đã kết nối' : 'Chưa kết nối'}</strong>
        <input type="password" aria-label={`Khóa API ${provider}`} autoComplete="off" placeholder="Nhập API key" value={keys[provider]} onChange={(event) => setKeys((current) => ({ ...current, [provider]: event.target.value }))} />
        <button type="button" disabled={!keys[provider] || Boolean(busy)} onClick={() => saveKey(provider)}>Lưu khóa</button>
        {settings.data?.keys[provider] && <button type="button" disabled={Boolean(busy)} onClick={() => removeKey(provider)}>Ngắt</button>}
      </div>)}</div>
      <div className="role-assignment-list">{roles.map(([role, label]) => <div className="role-assignment-row" key={role}>
        <strong>{label}</strong>
        <select aria-label={`AI cho ${label}`} value={assignments[role]?.provider || 'codex'} onChange={(event) => {
          const provider = event.target.value as AIProvider
          setAssignments((current) => ({ ...current, [role]: { provider, model: '' } }))
          void loadModels(provider)
        }}>{providers.map((provider) => <option key={provider} value={provider}>{provider === 'codex' ? 'Codex' : provider === 'claude' ? 'Claude' : 'Gemini'}</option>)}</select>
        <input aria-label={`Model cho ${label}`} list={`models-${role}`} placeholder={assignments[role]?.provider === 'codex' ? 'Mặc định tài khoản hoặc chọn model' : 'Chọn hoặc nhập model ID'} value={assignments[role]?.model || ''} onFocus={() => void loadModels(assignments[role]?.provider || 'codex')} onChange={(event) => setAssignments((current) => ({ ...current, [role]: { ...current[role], model: event.target.value } }))} />
        <datalist id={`models-${role}`}>{(models[assignments[role]?.provider || 'codex'] || []).map((model) => <option key={model} value={model} />)}</datalist>
      </div>)}</div>
      <button type="button" className="primary-button" disabled={Boolean(busy) || !settings.data} onClick={saveRoles}>{busy === 'roles' ? 'Đang lưu…' : 'Lưu cấu hình vai trò'}</button>
      {message && <p role="status">{message}</p>}
    </div>}
  </section>
}
