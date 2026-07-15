import type { Chemistry } from '../api/edge'

interface Props {
  chemistry: Chemistry
  capMid: number
}

function Row({ label, value, unit, highlight }: { label: string; value: string | number | null | undefined; unit?: string; highlight?: boolean }) {
  if (value == null) return null
  return (
    <div className={`flex justify-between items-center py-0.5 ${highlight ? 'text-white' : 'text-slate-300'}`}>
      <span className="text-slate-400 font-mono text-xs">{label}</span>
      <span className={`font-mono text-xs tabular-nums ${highlight ? 'text-emerald-400 font-semibold' : ''}`}>
        {typeof value === 'number' ? value.toFixed(3) : value}
        {unit && <span className="text-slate-500 ml-1">{unit}</span>}
      </span>
    </div>
  )
}

function OmegaBar({ omega }: { omega: number }) {
  const pct = Math.min(100, Math.max(0, ((omega - 1.2) / (4.0 - 1.2)) * 100))
  const color = omega < 1.2 ? 'bg-red-500' : omega < 2.0 ? 'bg-amber-500' : omega < 3.0 ? 'bg-blue-500' : 'bg-emerald-500'
  const label = omega < 1.2 ? 'BELOW SAFETY — HOLD' : omega < 2.0 ? 'Conservative' : omega < 3.0 ? 'Moderate ← CURRENT' : 'High capacity'
  return (
    <div className="mt-2 mb-1">
      <div className="flex justify-between text-[10px] text-slate-500 font-mono mb-1">
        <span>Ω 1.2 (safety)</span><span>2.0</span><span>3.0</span><span>4.0 (ideal)</span>
      </div>
      <div className="relative h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`absolute left-0 top-0 h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
        {/* threshold markers */}
        <div className="absolute top-0 h-full w-px bg-slate-500" style={{ left: '0%' }} />
        <div className="absolute top-0 h-full w-px bg-slate-500" style={{ left: `${((2.0 - 1.2) / 2.8) * 100}%` }} />
        <div className="absolute top-0 h-full w-px bg-slate-500" style={{ left: `${((3.0 - 1.2) / 2.8) * 100}%` }} />
      </div>
      <div className={`text-[10px] font-mono mt-1 ${color.replace('bg-', 'text-')}`}>{label}</div>
    </div>
  )
}

export function ChemistryPanel({ chemistry: c, capMid }: Props) {
  return (
    <details className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
      <summary className="px-4 py-3 cursor-pointer select-none flex items-center gap-2 text-slate-400 hover:text-slate-200 transition-colors text-sm font-semibold">
        <span>🔬</span>
        <span>Carbonate System Calculation</span>
        <span className="ml-auto text-xs font-mono text-slate-600">click to expand</span>
      </summary>

      <div className="px-4 pb-4 pt-1 grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">

        {/* Inputs */}
        <div>
          <h4 className="text-slate-500 uppercase tracking-widest text-[10px] font-bold mb-2">Sensor Inputs</h4>
          <Row label="pH (total scale)" value={c.input_pH} highlight />
          <Row label="pCO₂" value={c.input_pCO2} unit="µatm" highlight />
          <Row label="Temperature" value={c.input_temperature} unit="°C" />
          <Row label="Salinity" value={c.input_salinity} unit="PSU" />
          <Row label="Total Alkalinity" value={c.input_ta} unit="µmol/kg" />
          <div className="mt-2 pt-2 border-t border-slate-700">
            <span className="text-slate-500 text-[10px] font-mono">Method: </span>
            <span className="text-blue-400 text-[10px] font-mono">{c.carb_method ?? '—'}</span>
          </div>
        </div>

        {/* PyCO2SYS outputs */}
        <div>
          <h4 className="text-slate-500 uppercase tracking-widest text-[10px] font-bold mb-2">PyCO₂SYS Output</h4>
          <Row label="Ω aragonite" value={c.omega_aragonite} highlight />
          <Row label="DIC" value={c.dic} unit="µmol/kg" />
          <Row label="Alkalinity (calc)" value={c.alkalinity} unit="µmol/kg" />
          <Row label="Revelle Factor" value={c.revelle_factor} />
          <Row label="pH (computed)" value={c.pH_total} />
          <Row label="pCO₂ (computed)" value={c.pCO2_out} unit="µatm" />
          <div className="mt-2 pt-2 border-t border-slate-700">
            <span className="text-slate-500 text-[10px] font-mono">Lueker 2000 · Dickson 1990 · Total scale</span>
          </div>
        </div>

        {/* Decision logic */}
        <div>
          <h4 className="text-slate-500 uppercase tracking-widest text-[10px] font-bold mb-2">Decision Logic</h4>
          {c.omega_aragonite != null && <OmegaBar omega={c.omega_aragonite} />}
          <div className="mt-3 space-y-1">
            {[
              { label: 'Ω < 1.2', action: 'cap = 0  (safety gate)', active: (c.omega_aragonite ?? 0) < 1.2 },
              { label: '1.2 ≤ Ω < 2.0', action: 'conservative', active: (c.omega_aragonite ?? 0) >= 1.2 && (c.omega_aragonite ?? 0) < 2.0 },
              { label: '2.0 ≤ Ω < 3.0', action: 'moderate', active: (c.omega_aragonite ?? 0) >= 2.0 && (c.omega_aragonite ?? 0) < 3.0 },
              { label: 'Ω ≥ 3.0', action: 'high capacity', active: (c.omega_aragonite ?? 0) >= 3.0 },
            ].map(r => (
              <div key={r.label} className={`flex justify-between text-[10px] font-mono px-2 py-0.5 rounded ${r.active ? 'bg-blue-900/50 text-blue-300 border border-blue-700' : 'text-slate-600'}`}>
                <span>{r.label}</span>
                <span>→ {r.action}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-2 border-t border-slate-700 flex justify-between text-[10px] font-mono">
            <span className="text-slate-500">cap_mid now</span>
            <span className="text-white font-semibold">{capMid.toFixed(1)} t/day</span>
          </div>
          <div className="flex justify-between text-[10px] font-mono">
            <span className="text-slate-500">headroom</span>
            <span className="text-slate-300">{c.headroom != null ? (c.headroom * 100).toFixed(1) : '—'}%</span>
          </div>
          <div className="flex justify-between text-[10px] font-mono">
            <span className="text-slate-500">uncertainty spread</span>
            <span className="text-slate-300">{c.spread != null ? (c.spread * 100).toFixed(1) : '—'}%</span>
          </div>
        </div>

      </div>
    </details>
  )
}
