import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api'

export function ReportPreview({ token, runId }: { token: string; runId: string }) {
  const [showSource, setShowSource] = useState(false)
  useEffect(() => setShowSource(false), [runId])
  const report = useQuery({
    queryKey: ['file', runId, 'REPORT.md'],
    queryFn: () => api.file(token, runId, 'REPORT.md'),
    retry: false,
    refetchInterval: (query) => query.state.data ? false : 4000,
  })
  return <div className="report-preview">
    <div className="report-preview-heading">
      <div><FileText size={18} /><strong>Báo cáo nghiên cứu</strong></div>
      {report.data && <button type="button" aria-pressed={showSource} onClick={() => setShowSource((value) => !value)}>{showSource ? 'Xem bản đọc' : 'Xem Markdown gốc'}</button>}
    </div>
    {report.data ? showSource
      ? <pre className="report-source">{report.data.content}</pre>
      : <article className="report-document"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{report.data.content}</ReactMarkdown></article>
      :
      <p>{report.isError ? 'Báo cáo đang được biên soạn hoặc kiểm tra.' : 'Đang tải báo cáo…'}</p>}
  </div>
}
