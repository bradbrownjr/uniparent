// Types mirror backend/uniparent/app.py responses.

export type Role = 'admin' | 'parent'
export interface Me { id: number; username: string; display_name: string; role: Role }

export interface State {
  off: boolean
  reason: '' | 'manual' | 'pause' | 'schedule' | 'group' | 'bonus'  // bonus = extra screen time (WiFi on)
  until: number | null
  detail: string
}

export interface Device {
  mac: string
  label: string
  kind: string
  group_id: number | null
  notes: string
  state: State
  online: boolean
  blocked: boolean
  wired: boolean
  known: boolean
  ap: string
  signal: number | null
  ip: string
  last_active: number | null
  last_seen: number | null
}

export interface Group {
  id: number
  name: string
  state: State
  next_off: { ts: number; label: string } | null
  devices: Device[]
}

export interface Status {
  now: number
  me: Me
  controller_error: string | null
  groups: Group[]
  ungrouped: Device[]
}

export interface LogEntry { id: number; ts: number; actor: string; action: string; target: string }

export interface ClientRow {
  mac: string
  name: string
  hostname: string
  oui: string
  ip: string
  online: boolean
  wired: boolean
  blocked: boolean
  ap: string
  signal: number | null
  first_seen: number | null
  last_seen: number | null
  last_active: number | null
  bytes_last_hour: number
  randomized_mac: boolean
  new: boolean
  managed: boolean
  label: string | null
  kind: string | null
  group_id: number | null
  notes: string
}

export interface GroupRow { id: number; name: string }
export interface ScheduleRow {
  id: number; group_id: number; days: string; start: string; end: string; enabled: number; label: string
}
export interface UserRow { id: number; username: string; display_name: string; role: Role; created: number }
export interface TrafficPoint { ts: number; bytes: number }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

/** fetch wrapper: JSON in/out, cookie session, CSRF header on writes, readable errors. */
export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = opts.method ?? (opts.body === undefined ? 'GET' : 'POST')
  const headers: Record<string, string> = {}
  if (method !== 'GET') headers['X-UniParent'] = '1'
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  let r: Response
  try {
    r = await fetch(path, {
      method, headers, credentials: 'same-origin',
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    })
  } catch {
    throw new ApiError(0, "Can't reach UniParent. Are you on the home WiFi?")
  }
  if (!r.ok) {
    let msg = `Something went wrong (${r.status})`
    try {
      const j = await r.json()
      if (typeof j.detail === 'string') msg = j.detail
      else if (Array.isArray(j.detail) && j.detail[0]?.msg) msg = j.detail[0].msg
    } catch { /* not JSON */ }
    throw new ApiError(r.status, msg)
  }
  return r.json() as Promise<T>
}
