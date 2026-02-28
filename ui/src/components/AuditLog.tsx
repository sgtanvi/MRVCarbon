import { useQuery } from '@tanstack/react-query'
import { fetchAuditLog, AuditEntry } from '../api/edge'

export function AuditLog() {
  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['audit_log'],
    queryFn: () => fetchAuditLog(20),
    refetchInterval: 15000,
  })

  if (isLoading) {
    return (
      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <p className="text-slate-500 text-sm">Loading audit log…</p>
      </div>
    )
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
        <h3 className="text-slate-400 text-xs font-semibold uppercase tracking-widest">
          Hash-Chained Audit Log
        </h3>
        <span className="text-slate-600 text-xs">HMAC-SHA256</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 border-b border-slate-700">
              <th className="text-left px-3 py-2">ID</th>
              <th className="text-left px-3 py-2">Time</th>
              <th className="text-right px-3 py-2">Low</th>
              <th className="text-right px-3 py-2">Mid</th>
              <th className="text-right px-3 py-2">High</th>
              <th className="text-right px-3 py-2">Ω</th>
              <th className="text-right px-3 py-2">Conf</th>
              <th className="text-left px-3 py-2">Hash</th>
              <th className="text-center px-3 py-2">Sync</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e: AuditEntry) => (
              <tr
                key={e.id}
                className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors"
              >
                <td className="px-3 py-1.5 text-slate-500">{e.id}</td>
                <td className="px-3 py-1.5 font-mono text-slate-400">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </td>
                <td className="px-3 py-1.5 text-right text-amber-400">
                  {e.cap_low.toFixed(1)}
                </td>
                <td className="px-3 py-1.5 text-right text-blue-400 font-bold">
                  {e.cap_mid.toFixed(1)}
                </td>
                <td className="px-3 py-1.5 text-right text-emerald-400">
                  {e.cap_high.toFixed(1)}
                </td>
                <td className="px-3 py-1.5 text-right text-slate-300">
                  {e.aragonite_saturation.toFixed(3)}
                </td>
                <td className="px-3 py-1.5 text-right text-slate-400">
                  {Math.round(e.confidence * 100)}%
                </td>
                <td className="px-3 py-1.5 font-mono text-slate-600 truncate max-w-24">
                  {e.row_hash?.slice(0, 10)}…
                </td>
                <td className="px-3 py-1.5 text-center">
                  {e.synced ? (
                    <span className="text-emerald-500">✓</span>
                  ) : (
                    <span className="text-amber-500">⋯</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
