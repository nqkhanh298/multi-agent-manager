import { Folder, Trash2 } from 'lucide-react'
import type { Project } from '../types'

export function ProjectList({
  projects, selectedId, onSelect, onDelete,
}: {
  projects: Project[]
  selectedId: string | null
  onSelect: (id: string) => void
  onDelete: (project: Project) => void
}) {
  return <div className="project-list">
    {projects.map((project) => <div className="project-row" key={project.id}>
      <button className={`project-item ${selectedId === project.id ? 'selected' : ''}`} onClick={() => onSelect(project.id)} title={project.name}>
        <Folder size={16} /><span>{project.name}</span>
      </button>
      <button className="project-delete" onClick={() => onDelete(project)} title={`Xóa dự án ${project.name}`} aria-label={`Xóa dự án ${project.name}`}>
        <Trash2 size={15} />
      </button>
    </div>)}
    {!projects.length && <p className="sidebar-empty">Tạo dự án đầu tiên để bắt đầu.</p>}
  </div>
}
