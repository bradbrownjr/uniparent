import { useState } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { api, type Me } from './api'

export default function Login({ onDone }: { onDone: (me: Me) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      onDone(await api<Me>('/api/login', { body: { username, password } }))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Box sx={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', p: 2 }}>
      <Card sx={{ width: '100%', maxWidth: 400, bgcolor: 'background.paper' }} variant="outlined">
        <CardContent sx={{ p: 4 }}>
          <Stack component="form" spacing={2.5} onSubmit={submit}>
            <Box sx={{ textAlign: 'center' }}>
              <Box component="img" src="/icon-192.png" alt="" sx={{ width: 72, height: 72, borderRadius: 4 }} />
              <Typography variant="h5" sx={{ mt: 1, fontWeight: 700 }}>UniParent</Typography>
              <Typography color="text.secondary">Sign in once and this phone stays signed in.</Typography>
            </Box>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)}
              autoComplete="username" autoCapitalize="none" required fullWidth />
            <TextField label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password" required fullWidth />
            <Button type="submit" variant="contained" size="large" disabled={busy}>Sign in</Button>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  )
}
