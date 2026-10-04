import type { Device, State } from './api'

const time = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const dayTime = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
const day = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'short', day: 'numeric' })

/** "7:00 AM" today, "Tue 7:00 AM" otherwise. */
export function when(ts: number): string {
  const d = new Date(ts * 1000)
  const today = new Date()
  const tomorrow = new Date(); tomorrow.setDate(today.getDate() + 1)
  if (d.toDateString() === today.toDateString()) return time.format(d)
  if (d.toDateString() === tomorrow.toDateString()) return `tomorrow ${time.format(d)}`
  return dayTime.format(d)
}

export function dayLabel(ts: number): string {
  const d = new Date(ts * 1000)
  const today = new Date()
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return day.format(d)
}

export function clock(ts: number): string {
  return time.format(new Date(ts * 1000))
}

export function ago(ts: number | null, now = Date.now() / 1000): string {
  if (!ts) return 'never'
  const s = Math.max(0, now - ts)
  if (s < 90) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} hr ago`
  return `${Math.round(s / 86400)} days ago`
}

/** "38 min left" / "1 hr 5 min left". */
export function left(until: number, now = Date.now() / 1000): string {
  const m = Math.max(1, Math.ceil((until - now) / 60))
  return m < 60 ? `${m} min left` : `${Math.floor(m / 60)} hr${m % 60 ? ` ${m % 60} min` : ''} left`
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}

/** Epoch seconds for the next 7:00 AM local. */
export function nextMorning(hour = 7): number {
  const d = new Date()
  const m = new Date(d.getFullYear(), d.getMonth(), d.getDate(), hour, 0, 0)
  if (m <= d) m.setDate(m.getDate() + 1)
  return Math.floor(m.getTime() / 1000)
}

/** One-line description of why WiFi is off and for how long. */
export function stateLine(st: State): string {
  if (!st.off) return st.reason === 'bonus' && st.until ? `Extra time — locks again at ${when(st.until)}` : 'WiFi is on'
  const until = st.until ? ` until ${when(st.until)}` : ''
  switch (st.reason) {
    case 'manual': return 'WiFi is off'
    case 'pause': return `WiFi is paused${until}`
    case 'schedule': return `${st.detail || 'Scheduled'} — off${until}`
    case 'group': return st.detail ? `${st.detail} — off${until}` : `Off with the rest${until}`
    default: return 'WiFi is off'
  }
}

/** Short status for a device row: what the controller actually shows, and when it disagrees with UniParent. */
export function deviceLine(d: Device): string {
  if (d.wired) return "Wired — can't be switched off here"
  if (!d.known) return 'Not seen on the network yet'
  if (d.pending) return d.state.off ? 'Turning off…' : 'Turning on…'
  if (d.state.off && !d.blocked) return 'Allowed in the UniFi app'
  if (!d.state.off && d.blocked) return 'Blocked in the UniFi app'
  if (d.state.reason === 'bonus' && d.state.until) return `Extra time · locks again at ${when(d.state.until)}`
  if (d.state.off) {
    if (d.state.reason === 'manual') return 'Off until you turn it back on'
    return d.state.until ? `Off until ${when(d.state.until)}` : 'WiFi off'
  }
  if (!d.online) return d.waiting ? 'WiFi on · waiting for it to rejoin…' : `Offline · seen ${ago(d.last_seen)}`
  const act = !d.last_active ? 'Idle'
    : Date.now() / 1000 - d.last_active < 600 ? 'Active now' : `Active ${ago(d.last_active)}`
  return d.ap ? `${act} · ${d.ap}` : act
}

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function daysLabel(days: string): string {
  const s = [...days].map(Number).sort()
  const key = s.join('')
  if (key === '0123456') return 'Every day'
  if (key === '01234') return 'Weekdays'
  if (key === '56') return 'Weekends'
  if (key === '01236') return 'School nights (Sun–Thu)'
  return s.map((i) => DAYS[i]).join(', ')
}

export function hhmm(s: string): string {
  const [h, m] = s.split(':').map(Number)
  return time.format(new Date(2000, 0, 1, h, m))
}
