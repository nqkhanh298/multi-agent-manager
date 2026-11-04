import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api } from '../api'

export function makePreviewDocument(html: string, css: string, js: string): string {
  const document = new DOMParser().parseFromString(html, 'text/html')
  document.querySelectorAll('script, link, base, meta[http-equiv], iframe, object, embed').forEach((node) => node.remove())
  const policy = document.createElement('meta')
  policy.httpEquiv = 'Content-Security-Policy'
  policy.content = "default-src 'none'; script-src data:; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; form-action 'none'"
  document.head.prepend(policy)
  const style = document.createElement('style')
  style.textContent = css
  document.head.append(style)
  const script = document.createElement('script')
  script.src = `data:text/javascript;charset=utf-8,${encodeURIComponent(js)}`
  document.body.append(script)
  return `<!doctype html>\n${document.documentElement.outerHTML}`
}

export function WebPreview({ token, runId }: { token: string; runId: string }) {
  const files = useQuery({
    queryKey: ['web-preview', runId],
    queryFn: () => Promise.all(['index.html', 'styles.css', 'app.js'].map((path) => api.file(token, runId, path))),
    retry: false,
    refetchInterval: (query) => query.state.data ? false : 5000,
  })
  const document = useMemo(() => files.data && makePreviewDocument(files.data[0].content, files.data[1].content, files.data[2].content), [files.data])
  if (files.isError) return <div className="preview-placeholder">Chưa có bản xem trước. Đợi Developer tạo đủ HTML, CSS và JavaScript.</div>
  if (!document) return <div className="preview-placeholder">Đang tải giao diện trò chơi…</div>
  return <div className="preview-frame"><div className="preview-label">Bản xem trước cách ly · Có thể tương tác trực tiếp</div><iframe title="Xem trước ứng dụng web" srcDoc={document} sandbox="allow-scripts" referrerPolicy="no-referrer" /></div>
}
