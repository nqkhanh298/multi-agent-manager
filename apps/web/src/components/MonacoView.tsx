import Editor, { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker'

;(self as unknown as { MonacoEnvironment: { getWorker: () => Worker } }).MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
}
loader.config({ monaco })

export default function MonacoView({ path, content, language }: { path: string; content: string; language: string }) {
  return <Editor height="100%" path={path} value={content} language={language} theme="vs-dark" options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13, lineHeight: 21, scrollBeyondLastLine: false, automaticLayout: true, padding: { top: 14 } }} />
}
