import { Decision } from '../api/edge'

interface Props {
  decision: Decision
}

export function EnvelopeGauge({ decision }: Props) {
  const { cap_low, cap_mid, cap_high } = decision
  const isSafe = cap_mid > 5

  return (
    <div className="bg-slate-800 rounded-2xl p-8 shadow-xl border border-slate-700">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-slate-400 text-sm font-semibold uppercase tracking-widest">
          Max Safe Discharge Rate
        </h2>
        <span
          className={`px-3 py-1 rounded-full text-xs font-bold ${
            isSafe
              ? 'bg-emerald-900 text-emerald-300'
              : 'bg-red-900 text-red-300'
          }`}
        >
          {isSafe ? 'DISCHARGE OK' : 'HOLD — LOW HEADROOM'}
        </span>
      </div>

      <div className="flex items-end justify-center gap-8 mt-2">
        {/* Cap Low */}
        <div className="text-center">
          <div className="text-3xl font-bold text-amber-400">
            {cap_low.toFixed(1)}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            LOW
            <br />
            <span className="text-slate-600">(conservative)</span>
          </div>
        </div>

        {/* Cap Mid — hero */}
        <div className="text-center">
          <div className="text-7xl font-black text-blue-400 leading-none">
            {cap_mid.toFixed(1)}
          </div>
          <div className="text-base font-semibold text-slate-300 mt-2">
            t/day — best estimate
          </div>
        </div>

        {/* Cap High */}
        <div className="text-center">
          <div className="text-3xl font-bold text-emerald-400">
            {cap_high.toFixed(1)}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            HIGH
            <br />
            <span className="text-slate-600">(ideal mixing)</span>
          </div>
        </div>
      </div>

      {/* Range bar */}
      <div className="mt-6">
        <div className="relative h-3 bg-slate-700 rounded-full">
          <div
            className="absolute h-3 bg-gradient-to-r from-amber-500 via-blue-500 to-emerald-500 rounded-full"
            style={{
              left: `${Math.min(90, (cap_low / 120) * 100)}%`,
              width: `${Math.min(90, ((cap_high - cap_low) / 120) * 100)}%`,
            }}
          />
          <div
            className="absolute w-4 h-4 bg-blue-400 rounded-full -top-0.5 ring-2 ring-blue-300"
            style={{ left: `calc(${Math.min(90, (cap_mid / 120) * 100)}% - 8px)` }}
          />
        </div>
        <div className="flex justify-between text-xs text-slate-600 mt-1">
          <span>0</span>
          <span>60</span>
          <span>120 t/day</span>
        </div>
      </div>

      {/* Aragonite */}
      <div className="mt-4 flex items-center gap-2 text-sm text-slate-400">
        <span>Ω Aragonite:</span>
        <span
          className={`font-mono font-semibold ${
            decision.aragonite_saturation < 1.2
              ? 'text-red-400'
              : decision.aragonite_saturation < 2.0
              ? 'text-amber-400'
              : 'text-emerald-400'
          }`}
        >
          {decision.aragonite_saturation.toFixed(3)}
        </span>
        <span className="text-slate-600 text-xs ml-2">
          (safety threshold: 1.2)
        </span>
      </div>

      <div className="mt-2 text-xs text-slate-600">
        Updated: {new Date(decision.timestamp).toLocaleTimeString()} UTC
      </div>
    </div>
  )
}
