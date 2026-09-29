import { useCallback, useEffect, useState } from 'react'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import IconButton from '@mui/material/IconButton'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import Add from '@mui/icons-material/Add'
import Delete from '@mui/icons-material/Delete'
import { api, type GroupRow, type Me, type UserRow } from './api'
import { useNotify } from './common'

export default function Settings({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [groups, setGroups] = useState<GroupRow[]>([])
  const [users, setUsers] = useState<UserRow[]>([])
  const [groupDlg, setGroupDlg] = useState<GroupRow | { id: 0; name: string } | null>(null)
  const [userDlg, setUserDlg] = useState<UserRow | 'new' | null>(null)
  const [confirmUnblock, setConfirmUnblock] = useState(false)
  const notify = useNotify()

  const load = useCallback(async () => {
    try {
      const [g, u] = await Promise.all([api<GroupRow[]>('/api/admin/groups'), api<UserRow[]>('/api/admin/users')])
      setGroups(g); setUsers(u)
    } catch (e) { notify((e as Error).message, true) }
  }, [notify])
  useEffect(() => { load() }, [load])

  async function run(p: Promise<unknown>, msg: string) {
    try { await p; notify(msg); await load(); onChanged() } catch (e) { notify((e as Error).message, true) }
  }

  return (
    <Stack spacing={2}>
      <Card variant="outlined">
        <CardContent sx={{ pb: 0 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Groups</Typography>
          <Typography variant="body2" color="text.secondary">One per child. Each gets its own big on/off button.</Typography>
        </CardContent>
        <List>
          {groups.map((g) => (
            <ListItem key={g.id} disablePadding secondaryAction={
              <IconButton edge="end" aria-label={`Delete ${g.name}`}
                onClick={() => run(api(`/api/admin/groups/${g.id}`, { method: 'DELETE' }), `Deleted ${g.name}`)}><Delete /></IconButton>}>
              <ListItemButton onClick={() => setGroupDlg(g)}><ListItemText primary={g.name} /></ListItemButton>
            </ListItem>
          ))}
        </List>
        <CardContent sx={{ pt: 0 }}><Button startIcon={<Add />} onClick={() => setGroupDlg({ id: 0, name: '' })}>Add group</Button></CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent sx={{ pb: 0 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>People who can use UniParent</Typography>
          <Typography variant="body2" color="text.secondary">Parents can switch WiFi; admins can also set up devices and schedules.</Typography>
        </CardContent>
        <List>
          {users.map((u) => (
            <ListItemButton key={u.id} onClick={() => setUserDlg(u)}>
              <ListItemText primary={u.display_name} secondary={`${u.username} · ${u.role === 'admin' ? 'Admin' : 'Parent'}`} />
            </ListItemButton>
          ))}
        </List>
        <CardContent sx={{ pt: 0 }}><Button startIcon={<Add />} onClick={() => setUserDlg('new')}>Add person</Button></CardContent>
      </Card>

      <Card variant="outlined" sx={{ borderColor: 'error.main' }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Unblock everything</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Turns every device back on, clears pauses and switches all schedules off. Use it if something gets stuck.
          </Typography>
          <Button color="error" variant="outlined" onClick={() => setConfirmUnblock(true)}>Unblock everything</Button>
        </CardContent>
      </Card>

      {groupDlg && <GroupDialog group={groupDlg} onClose={() => setGroupDlg(null)} onSave={(name) => {
        setGroupDlg(null)
        run(groupDlg.id ? api(`/api/admin/groups/${groupDlg.id}`, { method: 'PUT', body: { name } })
          : api('/api/admin/groups', { body: { name } }), `Saved ${name}`)
      }} />}
      {userDlg && <UserDialog user={userDlg === 'new' ? null : userDlg} me={me} onClose={() => setUserDlg(null)}
        onDone={(p, msg) => { setUserDlg(null); run(p, msg) }} />}
      <Dialog open={confirmUnblock} onClose={() => setConfirmUnblock(false)}>
        <DialogTitle>Unblock everything?</DialogTitle>
        <DialogContent><DialogContentText>
          Every managed device gets WiFi back and all schedules are switched off until you turn them on again.
        </DialogContentText></DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmUnblock(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={() => {
            setConfirmUnblock(false)
            run(api('/api/admin/unblock-all', { body: {} }), 'Everything is unblocked')
          }}>Unblock everything</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}

function GroupDialog({ group, onClose, onSave }: { group: { id: number; name: string }; onClose: () => void; onSave: (n: string) => void }) {
  const [name, setName] = useState(group.name)
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{group.id ? 'Rename group' : 'New group'}</DialogTitle>
      <DialogContent>
        <TextField label="Child's name" value={name} onChange={(e) => setName(e.target.value)} fullWidth autoFocus sx={{ mt: 1 }} />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim()} onClick={() => onSave(name.trim())}>Save</Button>
      </DialogActions>
    </Dialog>
  )
}

function UserDialog({ user, me, onClose, onDone }: {
  user: UserRow | null; me: Me; onClose: () => void; onDone: (p: Promise<unknown>, msg: string) => void
}) {
  const [username, setUsername] = useState(user?.username ?? '')
  const [name, setName] = useState(user?.display_name ?? '')
  const [role, setRole] = useState(user?.role ?? 'parent')
  const [password, setPassword] = useState('')
  const self = user?.id === me.id
  const valid = user ? (password === '' || password.length >= 8) : username.trim() && password.length >= 8

  function save() {
    if (!user) {
      onDone(api('/api/admin/users', { body: { username: username.trim(), display_name: name.trim(), password, role } }),
        `Added ${name || username}`)
    } else {
      const body: Record<string, string> = { display_name: name.trim() }
      if (!self) body.role = role
      if (password) body.password = password
      onDone(api(`/api/admin/users/${user.id}`, { method: 'PUT', body }), 'Saved')
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{user ? `Edit ${user.display_name}` : 'Add person'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} disabled={!!user}
            autoCapitalize="none" />
          <TextField label="Display name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField select label="Role" value={role} onChange={(e) => setRole(e.target.value as UserRow['role'])} disabled={self}
            helperText={self ? "You can't change your own role" : ' '}>
            <MenuItem value="parent">Parent — on/off and pauses</MenuItem>
            <MenuItem value="admin">Admin — also devices, schedules, people</MenuItem>
          </TextField>
          <TextField label={user ? 'New password (leave blank to keep)' : 'Password'} type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="new-password"
            helperText={user && password ? 'Their phones will need to sign in again.' : 'At least 8 characters'} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {user && !self && <Button color="error" sx={{ mr: 'auto' }}
          onClick={() => onDone(api(`/api/admin/users/${user.id}`, { method: 'DELETE' }), `Removed ${user.display_name}`)}>Remove</Button>}
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!valid}>Save</Button>
      </DialogActions>
    </Dialog>
  )
}
