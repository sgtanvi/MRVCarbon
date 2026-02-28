import axios from 'axios'

const EDGE_URL = import.meta.env.VITE_EDGE_URL || 'http://localhost:8001'
const CLOUD_URL = import.meta.env.VITE_CLOUD_URL || 'http://localhost:8002'

export interface Decision {
  timestamp: string
  cap_low: number
  cap_mid: number
  cap_high: number
  reason_codes: string[]
  confidence: number
  aragonite_saturation: number
  source: string
  row_hash?: string
  decision_id?: number
}

export interface Status {
  status: string
  replay_index: number
  total_rows: number
  unsynced_decisions: number
  decision_interval_s: number
  data_source: string
  timestamp: string
}

export interface AuditEntry {
  id: number
  timestamp: string
  cap_low: number
  cap_mid: number
  cap_high: number
  confidence: number
  aragonite_saturation: number
  source: string
  row_hash: string
  synced: boolean
}

export const fetchDecision = async (): Promise<Decision> => {
  const { data } = await axios.get(`${EDGE_URL}/decision`)
  return data
}

export const fetchStatus = async (): Promise<Status> => {
  const { data } = await axios.get(`${EDGE_URL}/status`)
  return data
}

export const fetchAuditLog = async (limit = 20): Promise<AuditEntry[]> => {
  const { data } = await axios.get(`${EDGE_URL}/audit_log?limit=${limit}`)
  return data.entries
}

export type FaultMode = 'normal' | 'ph_flatline' | 'ph_spike'

export const fetchFaultMode = async (): Promise<FaultMode> => {
  const { data } = await axios.get(`${EDGE_URL}/fault`)
  return data.mode
}

export const setFaultMode = async (mode: FaultMode): Promise<void> => {
  await axios.post(`${EDGE_URL}/fault`, { mode })
}

export const getExportUrl = (dateStr?: string) => {
  const d = dateStr || new Date().toISOString().slice(0, 10)
  return `${CLOUD_URL}/export?date_str=${d}`
}

export const getMrvNoteUrl = (dateStr?: string) => {
  const d = dateStr || new Date().toISOString().slice(0, 10)
  return `${CLOUD_URL}/mrv_note?date_str=${d}`
}
