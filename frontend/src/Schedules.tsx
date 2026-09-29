import { useCallback, useEffect, useState } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Typography from '@mui/material/Typography'
import Add from '@mui/icons-material/Add'
import { api, type GroupRow, type ScheduleRow } from './api'
import { useNotify } from './common'
import { DAYS, daysLabel, hhmm } from './format'

type Draft = Omit<ScheduleRow, 'id'> & { id?: number }

const PRESETS: [string, string][] = [['01236', 'School nights'], ['01234', 'Weekdays'], ['56', 'Weekends'], ['0123456', 'Every day']]

export default function Schedules({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<ScheduleRow[] | null>(null)
  const [groups, setGroups] = useState<GroupRow[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)
  const notify = useNotify()

  const load = useCallback(async () => {
    try {
      const [s, g] = await Promise.all([api<ScheduleRow[]>('/api/admin/schedules'), api<GroupRow[]>('/api/admin/groups')])
      setRows(s); setGroups(g)
    } catch (e) { notify((e as Error).message, true) }
  }, [notify])
  useEffect(() => { load() }, [load])

  async function save(d: Draft) {
    try {
      const body = { group_id: d.group_id, days: d.days, start: d.start, end: d.end, enabled: !!d.enabled, label: d.label }
      if (d.id) await api(`/api/admin/schedules/${d.id}`, { method: 'PUT', body })
      else await api('/api/admin/schedules', { body })
      setDraft(null); await load(); onChanged(); notify('Schedule saved')
    } catch (e) { notify((e as Error).message, true) }
  }

  async function remove(id: number) {
    try {
      await api(`/api/admin/schedules/${id}`, { method: 'DELETE' })
      setDraft(null); await load(); onChanged(); notify('Schedule deleted')
    } catch (e) { notify((e as Error).message, true) }
  }

  if (!rows) return null
  if (groups.length === 0) return <Alert severity="info">Add a child first — in <b>Settings</b>, or while naming a device in <b>Devices</b>.</Alert>

  return (
    <Stack spacing={2}>
      <Typography color="text.secondary">
        During a schedule the child's WiFi is off. Tapping <b>Turn WiFi back on</b> during one skips just that time.
      </Typography>
      {groups.map((g) => {
        const mine = rows.filter((r) => r.group_id === g.id)
        return (
          <Card key={g.id} variant="outlined">
            <CardContent sx={{ pb: 0 }}><Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{g.name}</Typography></CardContent>
            <List>
              {mine.map((s) => (
                <ListItem key={s.id} disablePadding secondaryAction={
                  <Switch edge="end" checked={!!s.enabled} onChange={() => save({ ...s, enabled: s.enabled ? 0 : 1 })} />
                }>
                  <ListItemButton onClick={() => setDraft(s)}>
                    <ListItemText primary={`${s.label || 'Off'}: ${hhmm(s.start)} – ${hhmm(s.end)}`}
                      secondary={daysLabel(s.days)} />
                  </ListItemButton>
                </ListItem>
              ))}
              {mine.length === 0 && <ListItem><ListItemText secondary="No schedules" /></ListItem>}
            </List>
            <CardContent sx={{ pt: 0 }}>
              <Button startIcon={<Add />} onClick={() => setDraft({ group_id: g.id, days: '01236', start: '21:00',
                end: '07:00', enabled: 1, label: 'Bedtime' })}>Add schedule</Button>
            </CardContent>
          </Card>
        )
      })}
      {draft && <ScheduleDialog draft={draft} groups={groups} onClose={() => setDraft(null)} onSave={save}
        onDelete={draft.id ? () => remove(draft.id!) : undefined} />}
    </Stack>
  )
}

function ScheduleDialog({ draft, groups, onClose, onSave, onDelete }: {
  draft: Draft; groups: GroupRow[]; onClose: () => void; onSave: (d: Draft) => void; onDelete?: () => void
}) {
  const [d, setD] = useState(draft)
  const days = [...d.days]
  const overnight = d.end <= d.start
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{d.id ? 'Edit schedule' : 'New schedule'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ pt: 1 }}>
          <TextField label="Name" placeholder="Bedtime, Homework…" value={d.label} onChange={(e) => setD({ ...d, label: e.target.value })} />
          <TextField select label="Child" value={d.group_id} onChange={(e) => setD({ ...d, group_id: Number(e.target.value) })}>
            {groups.map((g) => <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>)}
          </TextField>
          <Stack direction="row" spacing={2}>
            <TextField label="WiFi off at" type="time" value={d.start} onChange={(e) => setD({ ...d, start: e.target.value })} fullWidth />
            <TextField label="Back on at" type="time" value={d.end} onChange={(e) => setD({ ...d, end: e.target.value })} fullWidth
              helperText={overnight ? 'next morning' : ' '} />
          </Stack>
          <div>
            <Typography variant="body2" sx={{ mb: 1 }}>Starts on</Typography>
            <ToggleButtonGroup value={days} onChange={(_, v: string[]) => setD({ ...d, days: [...v].sort().join('') })}
              size="small" fullWidth>
              {DAYS.map((name, i) => <ToggleButton key={i} value={String(i)} sx={{ px: 0 }}>{name[0]}</ToggleButton>)}
            </ToggleButtonGroup>
            <Stack direction="row" sx={{ gap: 1, mt: 1, flexWrap: 'wrap' }}>
              {PRESETS.map(([v, l]) => <Button key={v} size="small" variant={d.days === v ? 'contained' : 'text'}
                onClick={() => setD({ ...d, days: v })}>{l}</Button>)}
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {overnight ? 'An overnight schedule belongs to the day it starts: "School nights" = Sun–Thu evenings.' : ' '}
            </Typography>
          </div>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {onDelete && <Button color="error" onClick={onDelete} sx={{ mr: 'auto' }}>Delete</Button>}
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => onSave(d)} disabled={!d.days || d.start === d.end}>Save</Button>
      </DialogActions>
    </Dialog>
  )
}
