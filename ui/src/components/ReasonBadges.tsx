interface Props {
  codes: string[]
}

function badgeStyle(code: string): string {
  // Hard faults — red
  if (
    code.includes('MISSING') || code.includes('BELOW') || code.includes('PENALTY') ||
    code.includes('STUCK') || code.includes('DROPOUT') || code.includes('OOR') ||
    code.includes('IMPLAUSIBLE') || code.includes('PLAUSIBILITY_FAIL')
  ) {
    return 'bg-red-900 text-red-300 border border-red-700'
  }
  // Soft warnings — amber
  if (
    code.includes('SYNTHETIC') || code.includes('LOW') || code.includes('ELEVATED') ||
    code.includes('HIGH:') || code.includes('DRIFT')
  ) {
    return 'bg-amber-900 text-amber-300 border border-amber-700'
  }
  // Info — blue
  if (code.includes('OMEGA') || code.includes('HEADROOM') || code.includes('CARB') || code.includes('TIDAL')) {
    return 'bg-blue-900 text-blue-300 border border-blue-700'
  }
  return 'bg-slate-700 text-slate-300 border border-slate-600'
}

export function ReasonBadges({ codes }: Props) {
  if (!codes.length) return null

  return (
    <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <h3 className="text-slate-400 text-xs font-semibold uppercase tracking-widest mb-3">
        Decision Reason Codes
      </h3>
      <div className="flex flex-wrap gap-2">
        {codes.map((code, i) => (
          <span
            key={i}
            className={`text-xs px-2 py-1 rounded-md font-mono ${badgeStyle(code)}`}
          >
            {code}
          </span>
        ))}
      </div>
    </div>
  )
}
