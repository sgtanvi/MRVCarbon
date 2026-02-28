interface Props {
  confidence: number
  source: string
  unsynced?: number
}

export function ConfidenceBar({ confidence, source, unsynced = 0 }: Props) {
  const pct = Math.round(confidence * 100)
  const color =
    pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500'

  const sourceLabel =
    source === 'synthetic_seed'
      ? 'Synthetic (M1 statistics)'
      : source === 'mbari_live'
      ? 'MBARI M1 Live'
      : source

  return (
    <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-slate-400 text-xs font-semibold uppercase tracking-widest">
          Sensor Confidence
        </h3>
        <span className="text-slate-500 text-xs">Source: {sourceLabel}</span>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex-1 bg-slate-700 rounded-full h-4">
          <div
            className={`h-4 rounded-full transition-all duration-500 ${color}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-xl font-bold text-slate-200 w-14 text-right">
          {pct}%
        </span>
      </div>

      <div className="mt-2 flex items-center gap-4 text-xs">
        <span className="text-slate-500">
          pH: 35% · pCO₂: 25% · Temp: 20% · Sal: 12% · TA: 8%
        </span>
        {unsynced > 0 && (
          <span className="ml-auto text-amber-400 font-semibold">
            {unsynced} unsynced
          </span>
        )}
      </div>
    </div>
  )
}
