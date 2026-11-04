import type { ReferenceCheck, RunReference, RunEvent } from '../types'

export function RunReferences({ references, checks, events }: {
  references: RunReference[]
  checks: ReferenceCheck[]
  events: RunEvent[]
}) {
  if (!references.length) return null
  return <div className="run-references">
    <strong>Tài liệu và source tham chiếu ({references.length})</strong>
    <p>Nội dung đã trích được lưu cùng lượt chạy. Mở từng tài liệu để kiểm tra phần Codex nhận được.</p>
    {references.map((reference) => {
      const check = checks.find((item) => item.id === reference.id)
      const injected = events.some((event) => event.type === 'references.injected' && Array.isArray(event.payload.ids) && event.payload.ids.includes(reference.id))
      return <details key={reference.id} className="run-reference">
        <summary>{reference.name} {reference.kind === 'source' ? '(source tham chiếu)' : ''} <span>{check ? 'Đã đối chiếu mã nguồn' : injected ? 'Đã gửi tới agent' : 'Đang chờ agent'}</span></summary>
        <small>{reference.kind === 'source' ? `${reference.files_count} file · ` : ''}{reference.chars.toLocaleString('vi-VN')} ký tự · SHA-256: {reference.sha256.slice(0, 12)}…</small>
        {check && <div className="reference-evidence"><b>QA đối chiếu</b><p>Tài liệu: “{check.quote}”</p><p>Mã nguồn: {check.file} → <code>{check.evidence}</code></p></div>}
        <pre>{reference.text}</pre>
      </details>
    })}
  </div>
}
