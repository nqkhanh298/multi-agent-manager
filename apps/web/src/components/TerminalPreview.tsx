import { useState } from 'react'
import { api } from '../api'

export function TerminalPreview({ token, runId }: { token: string; runId: string }) {
  const [input, setInput] = useState('')
  const [output, setOutput] = useState('')
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    try {
      const result = await api.terminalPreview(token, runId, input)
      setOutput(`${result.stdout}${result.stderr ? `\n${result.stderr}` : ''}\n\n[Thoát: ${result.exit_code} · ${result.duration_ms} ms]`)
    } catch (error) {
      setOutput(error instanceof Error ? error.message : 'Không chạy được bản xem trước.')
    } finally {
      setBusy(false)
    }
  }

  return <div className="terminal-preview">
    <p>Chạy ứng dụng trong Docker. Nếu chương trình hỏi nhiều lần, nhập mỗi câu trả lời trên một dòng rồi bấm Chạy thử.</p>
    <label htmlFor="terminal-preview-input">Dữ liệu nhập cho chương trình</label>
    <textarea id="terminal-preview-input" value={input} onChange={(event) => setInput(event.target.value)} maxLength={4096} rows={4} placeholder="Ví dụ: mỗi câu trả lời một dòng" />
    <button type="button" className="primary-button" disabled={busy} onClick={run}>{busy ? 'Đang chạy…' : 'Chạy thử'}</button>
    <pre className="terminal-output" aria-live="polite">{output || 'Kết quả chạy sẽ hiện ở đây.'}</pre>
  </div>
}
