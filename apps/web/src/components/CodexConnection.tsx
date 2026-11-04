import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, ExternalLink } from 'lucide-react'
import { api } from '../api'
import type { CodexLogin } from '../types'

export function useCodexAccount(token: string) {
  return useQuery({
    queryKey: ['codex-account'],
    queryFn: () => api.codexAccount(token),
    retry: false,
    refetchInterval: 4000,
  })
}

export function CodexConnection({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const account = useCodexAccount(token)
  const [login, setLogin] = useState<CodexLogin | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function connect(method: 'browser' | 'device') {
    setBusy(true)
    setError('')
    try {
      setLogin(await api.codexLogin(token, method))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không thể bắt đầu đăng nhập Codex')
    } finally {
      setBusy(false)
    }
  }

  async function disconnect() {
    setBusy(true)
    setError('')
    try {
      await api.codexLogout(token)
      setLogin(null)
      await queryClient.invalidateQueries({ queryKey: ['codex-account'] })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không thể ngắt kết nối Codex')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="codex-connection panel" aria-label="Kết nối Codex">
      <div className="codex-connection-main"><Bot size={20} /><div><strong>Codex agents</strong><small>{account.data?.connected ? `Đã kết nối ${account.data.email || 'ChatGPT'}${account.data.plan_type ? ` · ${account.data.plan_type}` : ''}` : 'Kết nối tài khoản ChatGPT để chạy agent thật'}</small></div></div>
      <div className="codex-connection-actions">
        {account.data?.connected ? <button type="button" onClick={disconnect} disabled={busy}>Ngắt kết nối</button> : <><button type="button" onClick={() => connect('browser')} disabled={busy}>Kết nối ChatGPT</button><button type="button" onClick={() => connect('device')} disabled={busy}>Dùng mã thiết bị</button></>}
      </div>
      {login && !account.data?.connected && <div className="codex-login-instructions">
        {login.auth_url && <a href={login.auth_url} target="_blank" rel="noopener noreferrer">Mở trang đăng nhập ChatGPT <ExternalLink size={14} /></a>}
        {login.verification_url && <><a href={login.verification_url} target="_blank" rel="noopener noreferrer">Mở trang nhập mã <ExternalLink size={14} /></a><code>{login.user_code}</code></>}
        <small>Hoàn tất đăng nhập trong trình duyệt. Trạng thái sẽ tự cập nhật tại đây.</small>
      </div>}
      {(error || account.error) && <p className="codex-error">{error || (account.error instanceof Error ? account.error.message : 'Codex chưa sẵn sàng trong WSL')}</p>}
    </section>
  )
}
