import { useEffect, useState } from 'react'
import Avatar from '@mui/material/Avatar'
import Card from '@mui/material/Card'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemAvatar from '@mui/material/ListItemAvatar'
import ListItemText from '@mui/material/ListItemText'
import ListSubheader from '@mui/material/ListSubheader'
import Typography from '@mui/material/Typography'
import Person from '@mui/icons-material/Person'
import Schedule from '@mui/icons-material/Schedule'
import Timer from '@mui/icons-material/Timer'
import { api, type LogEntry } from './api'
import { useNotify } from './common'
import { clock, dayLabel } from './format'

export default function Activity({ refreshKey }: { refreshKey: number }) {
  const [rows, setRows] = useState<LogEntry[] | null>(null)
  const notify = useNotify()

  useEffect(() => {
    api<LogEntry[]>('/api/log?limit=200').then(setRows).catch((e) => notify(e.message, true))
  }, [refreshKey, notify])

  if (!rows) return null
  if (rows.length === 0) return <Typography color="text.secondary" sx={{ p: 2 }}>Nothing has happened yet.</Typography>

  const days: [string, LogEntry[]][] = []
  for (const r of rows) {
    const d = dayLabel(r.ts)
    if (!days.length || days[days.length - 1][0] !== d) days.push([d, []])
    days[days.length - 1][1].push(r)
  }
  return (
    <Card variant="outlined">
      <List disablePadding>
        {days.map(([d, entries]) => (
          <li key={d}>
            <ul style={{ padding: 0 }}>
              <ListSubheader sx={{ bgcolor: 'background.paper', fontWeight: 600 }}>{d}</ListSubheader>
              {entries.map((e) => (
                <ListItem key={e.id}>
                  <ListItemAvatar>
                    <Avatar sx={{ bgcolor: 'action.selected', color: 'text.primary' }}>
                      {e.actor === 'Schedule' ? <Schedule /> : e.actor === 'Timer' ? <Timer /> : <Person />}
                    </Avatar>
                  </ListItemAvatar>
                  <ListItemText
                    primary={e.target ? `${e.target}: ${e.action}` : e.action}
                    secondary={`${e.actor} · ${clock(e.ts)}`} />
                </ListItem>
              ))}
            </ul>
          </li>
        ))}
      </List>
    </Card>
  )
}
