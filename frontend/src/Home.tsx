import { useState } from 'react'
import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Divider from '@mui/material/Divider'
import List from '@mui/material/List'
import ListItemAvatar from '@mui/material/ListItemAvatar'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import Add from '@mui/icons-material/Add'
import Bedtime from '@mui/icons-material/Bedtime'
import CheckCircle from '@mui/icons-material/CheckCircle'
import Edit from '@mui/icons-material/Edit'
import HourglassTop from '@mui/icons-material/HourglassTop'
import Lock from '@mui/icons-material/Lock'
import Wifi from '@mui/icons-material/Wifi'
import WifiOff from '@mui/icons-material/WifiOff'
import { api, type ClientRow, type Device, type Group, type GroupRow, type Status } from './api'
import { EditDevice } from './Devices'
import { KindIcon, useNotify } from './common'
import { deviceLine, left, nextMorning, stateLine, when } from './format'

type Pause = { label: string; body: () => { minutes?: number; until?: number } }
const PAUSES: Pause[] = [
  { label: '30 min', body: () => ({ minutes: 30 }) },
  { label: '1 hour', body: () => ({ minutes: 60 }) },
  { label: '2 hours', body: () => ({ minutes: 120 }) },
  { label: 'Until 7 AM', body: () => ({ until: nextMorning() }) },
]
// Extra screen time: WiFi on for this long, then it locks again.
const EXTRA = [15, 30, 60, 120]
const extraLabel = (m: number, plus = false) => (plus ? '+' : '') + (m < 60 ? `${m} min` : `${m / 60} hour${m > 60 ? 's' : ''}`)

export type SetupTab = 'devices' | 'schedules'

export default function Home({ status, reload, isAdmin, go }: {
  status: Status | null; reload: () => Promise<void>; isAdmin: boolean; go: (t: SetupTab) => void
}) {
  if (!status) return null
  const hasDevices = status.groups.some((g) => g.devices.length > 0)
  const empty = status.groups.length === 0 && status.ungrouped.length === 0
  return (
    <Stack spacing={2}>
      {status.controller_error && (
        <Alert severity="warning">
          Can't talk to the WiFi controller right now, so changes may not take effect yet. It will keep trying.
        </Alert>
      )}
      {isAdmin && !hasDevices && <SetupCard groups={status.groups} reload={reload} go={go} />}
      {!isAdmin && empty && (
        <Card variant="outlined"><CardContent>
          <Typography variant="h6">Nothing set up yet</Typography>
          <Typography color="text.secondary">Ask the admin to add the kids and their devices.</Typography>
        </CardContent></Card>
      )}
      {status.groups.map((g) => <GroupCard key={g.id} group={g} reload={reload} isAdmin={isAdmin} />)}
      {status.ungrouped.length > 0 && (
        <Card variant="outlined">
          <CardContent sx={{ pb: 0 }}><Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Not assigned to a child</Typography></CardContent>
          <DeviceList devices={status.ungrouped} reload={reload} isAdmin={isAdmin} />
        </Card>
      )}
    </Stack>
  )
}

function GroupCard({ group: g, reload, isAdmin }: { group: Group; reload: () => Promise<void>; isAdmin: boolean }) {
  const notify = useNotify()
  const [busy, setBusy] = useState(false)
  const off = g.state.off
  const bonus = g.state.reason === 'bonus' && g.state.until !== null
  // Material 3 containers: saturated in light mode, deep tonal containers with light text in dark mode.
  // Green-teal = on, red = off, amber (tertiary) = extra time that will lock again.
  const dark = useTheme().palette.mode === 'dark'
  const cardBg = off ? (dark ? '#93000a' : 'error.main') : bonus ? (dark ? '#653e00' : '#8a5100') : (dark ? '#00504f' : 'primary.main')
  const cardFg = off ? (dark ? '#ffdad6' : '#ffffff') : bonus ? (dark ? '#ffdcbe' : '#ffffff') : (dark ? '#9cf1f4' : '#ffffff')
  const chipSx = { bgcolor: 'rgba(255,255,255,.18)', color: 'inherit', fontWeight: 500, height: 40, px: 0.5 }

  async function act(action: 'on' | 'off' | 'pause' | 'bonus' | 'endbonus', body?: object, msg?: string) {
    setBusy(true)
    try {
      const r = await api<{ controller_error: string | null }>(`/api/groups/${g.id}/${action}`, { body: body ?? {} })
      await reload()
      notify(r.controller_error ? 'Saved — the controller is not answering yet, it will retry.' : msg ?? 'Done')
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card sx={{ bgcolor: cardBg, color: cardFg, transition: 'background-color .3s' }}>
      <CardContent sx={{ p: 3 }}>
        <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
          <Avatar sx={{ width: 56, height: 56, bgcolor: 'rgba(255,255,255,.2)', color: 'inherit' }}>
            {off ? <WifiOff fontSize="large" /> : bonus ? <HourglassTop fontSize="large" /> : <Wifi fontSize="large" />}
          </Avatar>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>{g.name}</Typography>
            <Typography sx={{ opacity: 0.9 }}>{stateLine(g.state)}</Typography>
            {bonus && <Typography variant="body2" sx={{ fontWeight: 600 }}>{left(g.state.until!)}</Typography>}
            {g.devices.some((d) => d.pending) && (
              <Typography variant="body2" sx={{ fontWeight: 600 }}>Waiting for the WiFi controller to confirm…</Typography>
            )}
          </Box>
        </Stack>

        {bonus ? (
          <>
            <Button fullWidth size="large" variant="contained" disabled={busy}
              onClick={() => act('endbonus', undefined, `${g.name}'s extra time is over`)} startIcon={<Lock />}
              sx={{ mt: 3, py: 2, fontSize: '1.2rem', bgcolor: 'background.paper', color: 'error.main',
                '&:hover': { bgcolor: 'background.paper' } }}>
              Lock again now
            </Button>
            <Typography variant="body2" sx={{ mt: 2, mb: 1, opacity: 0.9 }}>Add more time:</Typography>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
              {EXTRA.slice(0, 3).map((m) => (
                <Chip key={m} label={extraLabel(m, true)} disabled={busy} sx={chipSx}
                  onClick={() => act('bonus', { minutes: m }, `Added ${extraLabel(m)} for ${g.name}`)} />
              ))}
            </Stack>
          </>
        ) : (
          <Button fullWidth size="large" variant="contained" disabled={busy}
            onClick={() => off ? act('on', undefined, `${g.name}'s WiFi is on`) : act('off', undefined, `${g.name}'s WiFi is off`)}
            startIcon={off ? <Wifi /> : <WifiOff />}
            sx={{ mt: 3, py: 2, fontSize: '1.2rem', bgcolor: 'background.paper', color: off ? 'success.main' : 'error.main',
              '&:hover': { bgcolor: 'background.paper' } }}>
            {off ? 'Turn WiFi back on' : 'Turn WiFi off'}
          </Button>
        )}

        {off && (
          <>
            <Typography variant="body2" sx={{ mt: 2, mb: 1, opacity: 0.9 }}>Earned more screen time? It locks again after:</Typography>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
              {EXTRA.map((m) => (
                <Chip key={m} label={extraLabel(m)} disabled={busy} icon={<HourglassTop sx={{ color: 'inherit !important' }} />}
                  sx={chipSx} onClick={() => act('bonus', { minutes: m }, `${g.name} has ${extraLabel(m)} of screen time`)} />
              ))}
            </Stack>
          </>
        )}

        {!off && !bonus && (
          <>
            <Typography variant="body2" sx={{ mt: 2, mb: 1, opacity: 0.9 }}>Or turn it off for a while:</Typography>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
              {PAUSES.map((p) => (
                <Chip key={p.label} label={p.label} disabled={busy} sx={chipSx}
                  onClick={() => act('pause', p.body(), `${g.name}'s WiFi is off for now`)} />
              ))}
            </Stack>
          </>
        )}
        {!off && !bonus && g.next_off && (
          <Stack direction="row" spacing={1} sx={{ mt: 2, alignItems: 'center', opacity: 0.9 }}>
            <Bedtime fontSize="small" />
            <Typography variant="body2">{g.next_off.label || 'Schedule'} starts {when(g.next_off.ts)}</Typography>
          </Stack>
        )}
      </CardContent>
      {g.devices.length > 0 && (
        <Box sx={{ bgcolor: 'background.paper', color: 'text.primary' }}>
          <DeviceList devices={g.devices} reload={reload} groupOff={off} isAdmin={isAdmin} />
        </Box>
      )}
    </Card>
  )
}

function DeviceList({ devices, reload, groupOff = false, isAdmin }: {
  devices: Device[]; reload: () => Promise<void>; groupOff?: boolean; isAdmin: boolean
}) {
  const [open, setOpen] = useState<Device | null>(null)
  const [editing, setEditing] = useState<{ client: ClientRow; groups: GroupRow[] } | null>(null)
  const notify = useNotify()

  async function edit(d: Device) {
    try {
      const [clients, groups] = await Promise.all([api<ClientRow[]>('/api/admin/clients'), api<GroupRow[]>('/api/admin/groups')])
      const client = clients.find((c) => c.mac === d.mac)
      if (!client) throw new Error(`${d.label} wasn't found on the controller`)
      setOpen(null)
      setEditing({ client, groups })
    } catch (e) { notify((e as Error).message, true) }
  }

  async function act(d: Device, action: 'on' | 'off' | 'hold' | 'pause' | 'bonus' | 'endbonus', body?: object) {
    try {
      await api(`/api/devices/${d.mac}/${action}`, { body: body ?? {} })
      await reload()
      notify(action === 'on' ? `${d.label} is back on` : action === 'bonus' ? `More screen time on ${d.label}`
        : action === 'endbonus' ? `${d.label} is locked again` : `${d.label} is off`)
    } catch (e) {
      notify((e as Error).message, true)
    }
  }

  return (
    <>
      <List disablePadding>
        {devices.map((d, i) => {
          // Show what the controller says, not what we asked for: on only once it has really let the device on.
          // Wired devices can't be switched, so never show them as off.
          const wifiOn = d.wired || (d.known ? !d.blocked : !d.state.off)
          const warn = (d.state.off !== d.blocked || d.pending) && !d.wired && d.known
          return (
            <Box key={d.mac}>
              {i > 0 && <Divider component="li" variant="inset" />}
              {/* Row button and switch are siblings (not nested): the switch gets its own full-height tap target
                  so a slightly-off tap toggles instead of opening the details dialog. */}
              <Stack direction="row" sx={{ alignItems: 'stretch' }}>
                <ListItemButton onClick={() => setOpen(d)} sx={{ py: 1.5, flex: 1, minWidth: 0 }}>
                  <ListItemAvatar>
                    <Avatar sx={{ bgcolor: wifiOn ? 'primary.main' : 'action.disabledBackground',
                      color: wifiOn ? 'primary.contrastText' : 'text.secondary' }}>
                      <KindIcon kind={d.kind} />
                    </Avatar>
                  </ListItemAvatar>
                  <ListItemText primary={d.label} secondary={deviceLine(d)}
                    slotProps={{ secondary: { color: warn ? 'warning.main' : 'text.secondary' } }} />
                  {d.online && wifiOn && d.last_active && Date.now() / 1000 - d.last_active < 600 && (
                    <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: 'success.main', mr: 1, flexShrink: 0 }}
                      title="Active in the last 10 minutes" />
                  )}
                </ListItemButton>
                {!d.wired && (
                  <Box onClick={(e) => e.stopPropagation()}
                    sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 80, flexShrink: 0 }}>
                    {d.pending && <CircularProgress size={16} sx={{ mr: 0.5 }} aria-label="Waiting for the controller" />}
                    <Switch checked={wifiOn} onChange={() => act(d, wifiOn ? 'off' : 'on')}
                      slotProps={{ input: { 'aria-label': `${d.label} WiFi` } }} />
                  </Box>
                )}
              </Stack>
            </Box>
          )
        })}
      </List>
      <Dialog open={!!open} onClose={() => setOpen(null)} fullWidth maxWidth="xs">
        {open && (
          <>
            <DialogTitle>{open.label}</DialogTitle>
            <DialogContent>
              <Typography color="text.secondary" sx={{ mb: 2 }}>{deviceLine(open)}</Typography>
              {!open.wired && (
                <>
                  <Typography variant="body2" sx={{ mb: 1 }}>Turn off just this device for:</Typography>
                  <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
                    {PAUSES.map((p) => (
                      <Chip key={p.label} label={p.label} variant="outlined"
                        onClick={() => { act(open, 'pause', p.body()); setOpen(null) }} />
                    ))}
                    <Chip label="Until I turn it back on" variant="outlined"
                      onClick={() => { act(open, 'hold'); setOpen(null) }} />
                  </Stack>
                  {!open.state.off && (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      The switch turns it off until WiFi next comes back on by schedule, or 7 AM.
                    </Typography>
                  )}
                  {(open.state.off || open.state.reason === 'bonus') && (
                    <>
                      <Typography variant="body2" sx={{ mt: 2.5, mb: 1 }}>
                        {open.state.reason === 'bonus' ? 'Add more time:' : 'Extra screen time on just this device (locks again after):'}
                      </Typography>
                      <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
                        {EXTRA.map((m) => (
                          <Chip key={m} label={extraLabel(m, open.state.reason === 'bonus')} color="warning" variant="outlined"
                            icon={<HourglassTop />} onClick={() => { act(open, 'bonus', { minutes: m }); setOpen(null) }} />
                        ))}
                      </Stack>
                    </>
                  )}
                  {groupOff && open.state.off && (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                      Turning this one on lets it back on while the rest stay off — handy for homework.
                    </Typography>
                  )}
                </>
              )}
            </DialogContent>
            <DialogActions>
              {isAdmin && <Button startIcon={<Edit />} onClick={() => edit(open)} sx={{ mr: 'auto' }}>Edit</Button>}
              <Button onClick={() => setOpen(null)}>Close</Button>
              {!open.wired && open.state.reason === 'bonus' && (
                <Button variant="contained" color="error" startIcon={<Lock />}
                  onClick={() => { act(open, 'endbonus'); setOpen(null) }}>Lock again now</Button>)}
              {!open.wired && open.state.reason !== 'bonus' && (open.state.off
                ? <Button variant="contained" color="success" onClick={() => { act(open, 'on'); setOpen(null) }}>Turn on</Button>
                : <Button variant="contained" color="error" onClick={() => { act(open, 'off'); setOpen(null) }}>Turn off</Button>)}
            </DialogActions>
          </>
        )}
      </Dialog>
      {editing && <EditDevice client={editing.client} groups={editing.groups} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); reload() }} />}
    </>
  )
}

// First-run checklist for admins: children first (schedules and the big buttons hang off them), then devices.
function SetupCard({ groups, reload, go }: { groups: Group[]; reload: () => Promise<void>; go: (t: SetupTab) => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const notify = useNotify()
  const haveKids = groups.length > 0

  async function add() {
    const n = name.trim()
    if (!n) return
    setBusy(true)
    try {
      await api('/api/admin/groups', { body: { name: n } })
      setName(''); notify(`Added ${n}`); await reload()
    } catch (e) { notify((e as Error).message, true) } finally { setBusy(false) }
  }

  const step = (n: number, done: boolean, title: string) => (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', mb: 1 }}>
      {done ? <CheckCircle color="success" /> : <Avatar sx={{ width: 24, height: 24, fontSize: 14, bgcolor: 'primary.main' }}>{n}</Avatar>}
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{title}</Typography>
    </Stack>
  )

  return (
    <Card variant="outlined"><CardContent>
      <Typography variant="h6" sx={{ mb: 2 }}>Let's get set up</Typography>
      {step(1, haveKids, 'Add your children')}
      <Box sx={{ pl: 4.5, mb: 2.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Each child gets a big on/off button here, and their own schedules.
        </Typography>
        {haveKids && <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
          {groups.map((g) => <Chip key={g.id} label={g.name} />)}
        </Stack>}
        <Stack direction="row" spacing={1} component="form" onSubmit={(e) => { e.preventDefault(); add() }}>
          <TextField size="small" label={haveKids ? 'Another child' : "Child's name"} value={name}
            onChange={(e) => setName(e.target.value)} fullWidth />
          <Button type="submit" variant={haveKids ? 'outlined' : 'contained'} startIcon={<Add />} disabled={busy || !name.trim()}>Add</Button>
        </Stack>
      </Box>
      {step(2, false, 'Name their devices')}
      <Box sx={{ pl: 4.5, mb: 2.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          In Devices, tap each of your child's phones, tablets and consoles, give it a name and pick the child.
        </Typography>
        <Button variant={haveKids ? 'contained' : 'outlined'} disabled={!haveKids} onClick={() => go('devices')}>Set up devices</Button>
      </Box>
      {step(3, false, 'Bedtime and homework (optional)')}
      <Box sx={{ pl: 4.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Schedules turn a child's WiFi off at set times, such as 9 PM – 7 AM on school nights.
        </Typography>
        <Button disabled={!haveKids} onClick={() => go('schedules')}>Add a schedule</Button>
      </Box>
    </CardContent></Card>
  )
}
