import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchDecision, fetchStatus, fetchFaultMode, setFaultMode, type FaultMode } from './api/edge'
import { EnvelopeGauge } from './components/EnvelopeGauge'
import { ReasonBadges } from './components/ReasonBadges'
import { ConfidenceBar } from './components/ConfidenceBar'
import { AuditLog } from './components/AuditLog'
import { ExportButton } from './components/ExportButton'

const FAULT_OPTIONS: { mode: FaultMode; label: string; description: string; color: string; active: string }[] = [
  {
    mode: 'normal',
    label: 'Normal Ops',
    description: 'Live sensor replay',
    color: 'border-slate-600 text-slate-400 hover:border-emerald-600 hover:text-emerald-400',
    active: 'border-emerald-500 bg-emerald-900/40 text-emerald-300',
  },
  {
    mode: 'ph_flatline',
    label: 'pH Flatline',
    description: 'Sensor stall / fouling',
    color: 'border-slate-600 text-slate-400 hover:border-amber-600 hover:text-amber-400',
    active: 'border-amber-500 bg-amber-900/40 text-amber-300',
  },
  {
    mode: 'ph_spike',
    label: 'pH Spike',
    description: 'Extreme outlier / failure',
    color: 'border-slate-600 text-slate-400 hover:border-red-600 hover:text-red-400',
    active: 'border-red-500 bg-red-900/40 text-red-300',
  },
]

export default function App() {
  const [activeFault, setActiveFault] = useState<FaultMode>('normal')
  const [faultPending, setFaultPending] = useState(false)

  const {
    data: decision,
    isLoading: decLoading,
    isError: decError,
  } = useQuery({
    queryKey: ['decision'],
    queryFn: fetchDecision,
    refetchInterval: 10000,
  })

  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: fetchStatus,
    refetchInterval: 10000,
  })

  // Sync initial fault mode from edge on load (one-time only)
  useEffect(() => {
    fetchFaultMode().then(setActiveFault).catch(() => {/* edge not yet ready */})
  }, [])

  const handleFault = async (mode: FaultMode) => {
    if (faultPending || mode === activeFault) return
    setFaultPending(true)
    try {
      await setFaultMode(mode)
      setActiveFault(mode)
    } finally {
      setFaultPending(false)
    }
  }

  const isFaulty = activeFault !== 'normal'

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-white">OAE MRV Dashboard</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Track 2A · Bicarbonate Ceiling · Operating Envelope
          </p>
        </div>
        <div className="flex items-center gap-3">
          {status && (
            <div className="text-right text-xs text-slate-500">
              <div>Replay idx: {status.replay_index} / {status.total_rows}</div>
              <div className={status.unsynced_decisions > 0 ? 'text-amber-400' : 'text-emerald-400'}>
                {status.unsynced_decisions > 0
                  ? `${status.unsynced_decisions} pending sync`
                  : 'Synced'}
              </div>
              <div>Source: {status.data_source}</div>
            </div>
          )}
          <div
            className={`w-3 h-3 rounded-full ${
              decError ? 'bg-red-500' : decLoading ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'
            }`}
          />
        </div>
      </div>

      {/* Fault Simulator Panel */}
      <div className={`rounded-xl border p-3 mb-4 transition-colors ${
        isFaulty ? 'border-red-700 bg-red-950/30' : 'border-slate-700 bg-slate-800/50'
      }`}>
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <span className={`text-xs font-bold font-mono tracking-widest uppercase ${
              isFaulty ? 'text-red-400' : 'text-slate-500'
            }`}>
              {isFaulty ? '⚠ FAULT SIM ACTIVE' : 'FAULT SIMULATOR'}
            </span>
          </div>
          <div className="flex gap-2">
            {FAULT_OPTIONS.map(opt => (
              <button
                key={opt.mode}
                onClick={() => handleFault(opt.mode)}
                disabled={faultPending}
                className={`px-3 py-1.5 rounded-lg border text-xs font-mono transition-all disabled:opacity-50 ${
                  activeFault === opt.mode ? opt.active : opt.color
                }`}
              >
                <div className="font-semibold">{opt.label}</div>
                <div className="text-[10px] opacity-70">{opt.description}</div>
              </button>
            ))}
          </div>
          {isFaulty && (
            <div className="ml-auto text-xs text-red-400 font-mono">
              {activeFault === 'ph_flatline'
                ? 'pH locked at 7.800 → STUCK_PH after ~10s'
                : 'pH injected at 6.20 → PLAUSIBILITY_FAIL · cap = 0'}
            </div>
          )}
        </div>
      </div>

      {/* Main content */}
      {decLoading && (
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-500 animate-pulse text-lg">
            Initializing edge MRV system…
          </div>
        </div>
      )}

      {decError && (
        <div className="bg-red-900/50 border border-red-700 rounded-xl p-6 text-center">
          <p className="text-red-300 font-semibold">Edge service unreachable</p>
          <p className="text-red-400 text-sm mt-1">
            Check that the edge container is running at{' '}
            {import.meta.env.VITE_EDGE_URL || 'http://localhost:8001'}
          </p>
        </div>
      )}

      {decision && decision.status === 'initializing' && (
        <div className="flex justify-center h-64">
          <div className="text-slate-500 animate-pulse text-lg">
            {decision.message || 'First decision pending…'}
          </div>
        </div>
      )}

      {decision && decision.status !== 'initializing' && (
        <div className="space-y-4 max-w-4xl mx-auto">
          {/* Hero gauge */}
          <EnvelopeGauge decision={decision} />

          {/* Confidence */}
          <ConfidenceBar
            confidence={decision.confidence}
            source={decision.source}
            unsynced={status?.unsynced_decisions}
          />

          {/* Reason codes */}
          <ReasonBadges codes={decision.reason_codes} />

          {/* Export */}
          <div className="flex justify-end">
            <ExportButton />
          </div>

          {/* Audit log */}
          <AuditLog />

          {/* Hash chain note */}
          {decision.row_hash && (
            <div className="text-xs text-slate-600 font-mono text-center">
              Latest hash: {decision.row_hash.slice(0, 32)}…
            </div>
          )}
        </div>
      )}
    </div>
  )
}
