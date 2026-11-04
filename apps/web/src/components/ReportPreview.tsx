import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import { api } from '../api'

export function ReportPreview({ token, runId }: { token: string; runId: string }) {
  const report = useQuery({
    queryKey: ['file', runId, 'REPORT.md'],
    queryFn: () => api.file(token, runId, 'REPORT.md'),
    retry: false,
    refetchInterval: (query) => query.state.data ? false : 4000,
  })
  return <div className="report-preview">
    <div className="report-preview-heading"><FileText size={18} /><strong>Báo cáo nghiên cứu</strong></div>
    {report.data ? <pre>{report.data.content}</pre> :
      <p>{report.isError ? 'Báo cáo đang được biên soạn hoặc kiểm tra.' : 'Đang tải báo cáo…'}</p>}
  </div>
}
