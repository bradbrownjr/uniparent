import { useCallback, useEffect, useMemo, useState } from 'react'
import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import Chip from '@mui/material/Chip'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Divider from '@mui/material/Divider'
import InputAdornment from '@mui/material/InputAdornment'
import List from '@mui/material/List'
import ListItemAvatar from '@mui/material/ListItemAvatar'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import Search from '@mui/icons-material/Search'
import { api, type ClientRow, type GroupRow, type TrafficPoint } from './api'
import { KINDS, KindIcon, Sparkline, useNotify } from './common'
import { ago, bytes } from './format'

type Filter = 'all' | 'new' | 'managed' | 'online' | 'busy'

export default function Devices({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<ClientRow[] | null>(null)
  const [groups, setGroups] = useState<GroupRow[]>([])
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [edit, setEdit] = useState<ClientRow | null>(null)
  const notify = useNotify()

  const load = useCallback(async () => {
    try {
      const [c, g] = await Promise.all([api<ClientRow[]>('/api/admin/clients'), api<GroupRow[]>('/api/admin/groups')])
      setRows(c); setGroups(g)
    } catch (e) { notify((e as Error).message, true) }
  }, [notify])
  useEffect(() => { load() }, [load])

  const shown = useMemo(() => {
    if (!rows) return []
    const needle = q.trim().toLowerCase()
    // MACs match however they're typed: aa:bb…, AA-BB…, aabb.cc…, or a fragment without separators.
    const hex = needle.replace(/[^0-9a-f]/g, '')
    const macLike = hex.length >= 4 && /^[0-9a-f:.\-\s]+$/.test(needle)
    let r = rows.filter((c) => !needle || [c.label, c.name, c.hostname, c.oui, c.ip, c.mac, c.ap]
      .some((v) => v?.toLowerCase().includes(needle)) || (macLike && c.mac.replace(/:/g, '').includes(hex)))
    if (filter === 'new') r = r.filter((c) => c.new)
    if (filter === 'managed') r = r.filter((c) => c.managed)
    if (filter === 'online') r = r.filter((c) => c.online)
    if (filter === 'busy') r = [...r].filter((c) => c.bytes_last_hour > 0).sort((a, b) => b.bytes_last_hour - a.bytes_last_hour)
    return r
  }, [rows, q, filter])

  if (!rows) return null
  const groupName = (id: number | null) => groups.find((g) => g.id === id)?.name
  const count = (f: Filter) => f === 'new' ? rows.filter((c) => c.new).length : f === 'managed' ? rows.filter((c) => c.managed).length
    : f === 'online' ? rows.filter((c) => c.online).length : null

  return (
    <Stack spacing={2}>
      {groups.length === 0 && (
        <Alert severity="info">Tap a device, name it, and pick <b>+ Add a child…</b> under <b>Child</b> to get started.</Alert>
      )}
      <TextField placeholder="Search name, hostname, IP, MAC, vendor…" value={q} onChange={(e) => setQ(e.target.value)}
        slotProps={{ input: { startAdornment: <InputAdornment position="start"><Search /></InputAdornment> } }} />
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
        {([['all', 'All'], ['managed', 'Labeled'], ['new', 'New'], ['online', 'Online'], ['busy', 'Busiest (1 hr)']] as [Filter, string][])
          .map(([f, label]) => {
            const n = count(f)
            return <Chip key={f} label={n === null ? label : `${label} ${n}`} color={filter === f ? 'primary' : 'default'}
              variant={filter === f ? 'filled' : 'outlined'} onClick={() => setFilter(f)} />
          })}
      </Stack>
      <Typography variant="body2" color="text.secondary">
        Tip: to find a child's device, have them use it and check <b>Busiest</b>, or look at which access point it's on.
      </Typography>
      <Card variant="outlined">
        <List disablePadding>
          {shown.map((c, i) => (
            <Box key={c.mac}>
              {i > 0 && <Divider component="li" variant="inset" />}
              <ListItemButton onClick={() => setEdit(c)} sx={{ py: 1.25 }}>
                <ListItemAvatar>
                  <Avatar sx={{ bgcolor: c.managed ? 'primary.main' : 'action.selected',
                    color: c.managed ? 'primary.contrastText' : 'text.secondary' }}>
                    <KindIcon kind={c.kind} />
                  </Avatar>
                </ListItemAvatar>
                <ListItemText
                  primary={<Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                    <span>{c.label ?? c.name}</span>
                    {c.new && <Chip size="small" color="warning" label="New" />}
                    {c.managed && groupName(c.group_id) && <Chip size="small" label={groupName(c.group_id)} />}
                    {c.blocked && <Chip size="small" color="error" label="Blocked" />}
                  </Stack>}
                  secondary={[
                    c.label && c.label !== c.name ? c.name : null,
                    c.hostname && c.hostname !== c.name && c.hostname !== c.label ? c.hostname : null,
                    c.oui && c.oui !== c.name ? c.oui : null,
                    c.online ? (c.wired ? 'Wired' : `${c.ap}${c.signal ? ` ${c.signal} dBm` : ''}`) : `Offline, seen ${ago(c.last_seen)}`,
                    c.bytes_last_hour ? `${bytes(c.bytes_last_hour)} last hr` : null,
                  ].filter(Boolean).join(' · ')} />
              </ListItemButton>
            </Box>
          ))}
          {shown.length === 0 && <Typography color="text.secondary" sx={{ p: 2 }}>No matching devices.</Typography>}
        </List>
      </Card>
      {edit && <EditDevice client={edit} groups={groups} onClose={() => setEdit(null)}
        onSaved={() => { setEdit(null); load(); onChanged() }} />}
    </Stack>
  )
}

const NEW_CHILD = -1

export function EditDevice({ client: c, groups: initialGroups, onClose, onSaved }: {
  client: ClientRow; groups: GroupRow[]; onClose: () => void; onSaved: () => void
}) {
  const [groups, setGroups] = useState(initialGroups)
  const [newChild, setNewChild] = useState<string | null>(null)
  const [label, setLabel] = useState(c.label ?? '')
  const [kind, setKind] = useState(c.kind ?? 'other')
  const [groupId, setGroupId] = useState<number | ''>(c.group_id ?? (c.managed ? '' : groups[0]?.id ?? ''))
  const [notes, setNotes] = useState(c.notes)
  const [traffic, setTraffic] = useState<TrafficPoint[] | null>(null)
  const notify = useNotify()
  const now = Math.floor(Date.now() / 1000)

  useEffect(() => {
    api<TrafficPoint[]>(`/api/admin/traffic/${c.mac}?hours=24`).then(setTraffic).catch(() => setTraffic([]))
  }, [c.mac])

  async function save() {
    try {
      await api(`/api/admin/devices/${c.mac}`, { method: 'PUT',
        body: { label: label.trim(), kind, group_id: groupId === '' ? null : groupId, notes } })
      notify(`Saved ${label.trim()}`)
      onSaved()
    } catch (e) { notify((e as Error).message, true) }
  }

  const childName = groups.find((g) => g.id === groupId)?.name

  async function addChild() {
    const name = newChild?.trim()
    if (!name) return
    try {
      const { id } = await api<{ id: number }>('/api/admin/groups', { body: { name } })
      setGroups([...groups, { id, name }].sort((a, b) => a.name.localeCompare(b.name)))
      setGroupId(id); setNewChild(null)
      notify(`Added ${name}`)
    } catch (e) { notify((e as Error).message, true) }
  }

  async function forget() {
    try {
      await api(`/api/admin/devices/${c.mac}`, { method: 'DELETE' })
      notify(`Stopped managing ${c.label}`)
      onSaved()
    } catch (e) { notify((e as Error).message, true) }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{c.managed ? 'Edit device' : 'Label this device'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Box sx={{ bgcolor: 'action.hover', borderRadius: 3, p: 2 }}>
            <Typography variant="body2"><b>{c.name}</b>{c.hostname && c.hostname !== c.name ? ` · ${c.hostname}` : ''}{c.oui && c.oui !== c.name ? ` · ${c.oui}` : ''}</Typography>
            <Typography variant="body2" color="text.secondary">
              {c.mac} · {c.ip || 'no IP'} · {c.online ? (c.wired ? 'wired' : `${c.ap}, ${c.signal} dBm`) : `offline, seen ${ago(c.last_seen)}`}
            </Typography>
            {c.wired && <Typography variant="body2" color="warning.main" sx={{ mt: 1 }}>
              Wired devices can't be switched off from UniFi without a UniFi gateway.</Typography>}
            {c.randomized_mac && <Typography variant="body2" color="warning.main" sx={{ mt: 1 }}>
              This device uses a private (randomized) WiFi address. On the device, set the private address for this
              network to <b>fixed / per-network</b>, or it may reappear as a new device.</Typography>}
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>Traffic, last 24 hours</Typography>
            {traffic && <Sparkline points={traffic} from={now - 86400} to={now} />}
            <Typography variant="caption" color="text.secondary">
              {traffic ? `${bytes(traffic.reduce((s, p) => s + p.bytes, 0))} total · last active ${ago(c.last_active)}` : ' '}
            </Typography>
          </Box>
          <TextField label="Name" placeholder={childName ? `e.g. ${childName}'s phone` : 'e.g. Upstairs tablet'} value={label} onChange={(e) => setLabel(e.target.value)}
            required autoFocus={!c.managed} />
          <TextField select label="Type" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => <MenuItem key={k.value} value={k.value}>
              <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}><KindIcon kind={k.value} fontSize="small" /><span>{k.label}</span></Stack>
            </MenuItem>)}
          </TextField>
          {newChild === null ? (
            <TextField select label="Child" value={groupId}
              onChange={(e) => {
                const v = e.target.value === '' ? '' : Number(e.target.value)
                if (v === NEW_CHILD) setNewChild('')
                else setGroupId(v)
              }}>
              {groups.map((g) => <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>)}
              <MenuItem value={NEW_CHILD} sx={{ color: 'primary.main' }}>+ Add a child…</MenuItem>
              <MenuItem value=""><em>Not assigned to a child</em></MenuItem>
            </TextField>
          ) : (
            <Stack direction="row" spacing={1} component="form" onSubmit={(e) => { e.preventDefault(); addChild() }}>
              <TextField label="New child's name" value={newChild} onChange={(e) => setNewChild(e.target.value)} fullWidth autoFocus />
              <Button type="submit" variant="contained" disabled={!newChild.trim()}>Add</Button>
              <Button onClick={() => setNewChild(null)}>Cancel</Button>
            </Stack>
          )}
          <TextField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} multiline minRows={2} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {c.managed && <Button color="error" onClick={forget} sx={{ mr: 'auto' }}>Stop managing</Button>}
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!label.trim() || newChild !== null}>Save</Button>
      </DialogActions>
    </Dialog>
  )
}
