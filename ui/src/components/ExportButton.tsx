import { getExportUrl, getMrvNoteUrl } from '../api/edge'

export function ExportButton() {
  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="flex gap-3">
      <a
        href={getMrvNoteUrl()}
        target="_blank"
        rel="noopener noreferrer"
        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-lg border border-slate-600 transition-colors"
      >
        View MRV Note
      </a>
      <a
        href={getExportUrl()}
        download={`mrv_note_${today}.html`}
        className="px-4 py-2 bg-blue-700 hover:bg-blue-600 text-white text-sm rounded-lg font-semibold transition-colors"
      >
        Export Daily MRV Note
      </a>
    </div>
  )
}
