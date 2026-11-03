import { useState } from 'react'
import { ArrowRight, KeyRound, Layers3, LockKeyhole } from 'lucide-react'
import { api } from '../api'
import { useUI } from '../store'

export function Login() {
  const [candidate, setCandidate] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const setToken = useUI((state) => state.setToken)

  async function connect(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.projects(candidate.trim())
      setToken(candidate.trim())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Không thể kết nối API')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-shell">
      <div className="login-glow" />
      <div className="login-brand"><span className="brand-mark"><Layers3 size={24} /></span><span>AI Coding Studio</span></div>
      <div className="login-card">
        <span className="eyebrow"><LockKeyhole size={14} /> Kết nối cục bộ</span>
        <h1>Xem hệ thống đang xây dựng dự án.</h1>
        <p>Dashboard này đọc trạng thái thật từ API M4. Nhập token của tài khoản cục bộ để xem dự án và chạy benchmark.</p>
        <form onSubmit={connect}>
          <label htmlFor="api-token">API token</label>
          <div className="login-input"><KeyRound size={18} /><input id="api-token" type="password" value={candidate} onChange={(event) => setCandidate(event.target.value)} placeholder="Dán token từ bootstrap" autoComplete="off" required /></div>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="primary-button login-submit" type="submit" disabled={busy || !candidate.trim()}>{busy ? 'Đang kết nối…' : 'Vào dashboard'} <ArrowRight size={17} /></button>
        </form>
        <div className="login-hint"><strong>Lấy token dùng thử</strong><code>wsl -d Ubuntu -- bash -lc 'cat ~/projects/ai-coding-platform/.local/platform/local-api-token.txt'</code><small>Token chỉ được lưu trong phiên trình duyệt hiện tại.</small></div>
      </div>
      <div className="login-footer">M5 dashboard · kết nối API M4 · chạy cục bộ trên WSL2</div>
    </main>
  )
}
