import { useCallback, useEffect, useMemo, useState } from 'react'
import Alert from '@mui/material/Alert'
import AppBar from '@mui/material/AppBar'
import BottomNavigation from '@mui/material/BottomNavigation'
import BottomNavigationAction from '@mui/material/BottomNavigationAction'
import Box from '@mui/material/Box'
import CircularProgress from '@mui/material/CircularProgress'
import Container from '@mui/material/Container'
import IconButton from '@mui/material/IconButton'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Paper from '@mui/material/Paper'
import Snackbar from '@mui/material/Snackbar'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import AccountCircle from '@mui/icons-material/AccountCircle'
import Devices from '@mui/icons-material/Devices'
import History from '@mui/icons-material/History'
import Home from '@mui/icons-material/Home'
import Schedule from '@mui/icons-material/Schedule'
import SettingsIcon from '@mui/icons-material/Settings'
import { ApiError, api, type Me, type Status } from './api'
import { Notify } from './common'
import Activity from './Activity'
import DevicesPage from './Devices'
import HomePage from './Home'
import Login from './Login'
import Schedules from './Schedules'
import Settings from './Settings'

type Tab = 'home' | 'activity' | 'devices' | 'schedules' | 'settings'
const TITLES: Record<Tab, string> = {
  home: 'UniParent', activity: 'Activity', devices: 'Devices', schedules: 'Schedules', settings: 'Settings',
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined)  // undefined = still checking
  const [status, setStatus] = useState<Status | null>(null)
  const [tab, setTab] = useState<Tab>('home')
  const [toast, setToast] = useState<{ msg: string; error: boolean } | null>(null)
  const [menu, setMenu] = useState<HTMLElement | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [offline, setOffline] = useState(false)

  const notify = useCallback((msg: string, error = false) => setToast({ msg, error }), [])

  const reload = useCallback(async () => {
    try {
      setStatus(await api<Status>('/api/status'))
      setOffline(false)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null)
      else setOffline(true)
    }
  }, [])

  useEffect(() => {
    api<Me>('/api/me').then(setMe).catch((e) => setMe(e instanceof ApiError && e.status === 401 ? null : null))
  }, [])

  // Keep the home screen fresh while it's open; refresh immediately when the app comes back to the front.
  useEffect(() => {
    if (!me) return
    reload()
    const t = setInterval(() => { if (document.visibilityState === 'visible') reload() }, 15000)
    const onVis = () => { if (document.visibilityState === 'visible') { reload(); setRefreshKey((k) => k + 1) } }
    document.addEventListener('visibilitychange', onVis)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVis) }
  }, [me, reload])

  const tabs = useMemo(() => {
    const t: [Tab, string, React.ReactNode][] = [['home', 'Home', <Home />], ['activity', 'Activity', <History />]]
    if (me?.role === 'admin') t.push(['devices', 'Devices', <Devices />], ['schedules', 'Schedules', <Schedule />],
      ['settings', 'Settings', <SettingsIcon />])
    return t
  }, [me])

  async function signOut() {
    setMenu(null)
    try { await api('/api/logout', { body: {} }) } catch { /* ignore */ }
    setMe(null); setStatus(null); setTab('home')
  }

  if (me === undefined) return <Box sx={{ minHeight: '100dvh', display: 'grid', placeItems: 'center' }}><CircularProgress /></Box>
  if (me === null) return <Login onDone={(m) => { setMe(m); setTab('home') }} />

  const changed = () => { reload() }
  return (
    <Notify.Provider value={notify}>
      <AppBar position="sticky" sx={{ bgcolor: 'background.default', color: 'text.primary', pt: 'env(safe-area-inset-top)' }}>
        <Container maxWidth="sm" disableGutters>
          <Toolbar>
            {tab === 'home' && <Box component="img" src="/icon-192.png" alt="" sx={{ width: 32, height: 32, borderRadius: 2, mr: 1.5 }} />}
            <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 600 }}>{TITLES[tab]}</Typography>
            <IconButton edge="end" aria-label="Account" onClick={(e) => setMenu(e.currentTarget)}><AccountCircle /></IconButton>
            <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
              <MenuItem disabled>{me.display_name} · {me.role === 'admin' ? 'Admin' : 'Parent'}</MenuItem>
              <MenuItem onClick={signOut}>Sign out</MenuItem>
            </Menu>
          </Toolbar>
        </Container>
      </AppBar>

      <Container maxWidth="sm" sx={{ pt: 1, pb: 'calc(96px + env(safe-area-inset-bottom))' }}>
        {offline && <Alert severity="error" sx={{ mb: 2 }}>Can't reach UniParent. Are you on the home WiFi?</Alert>}
        {tab === 'home' && <HomePage status={status} reload={reload} isAdmin={me.role === 'admin'} go={setTab} />}
        {tab === 'activity' && <Activity refreshKey={refreshKey} />}
        {tab === 'devices' && <DevicesPage onChanged={changed} />}
        {tab === 'schedules' && <Schedules onChanged={changed} />}
        {tab === 'settings' && <Settings me={me} onChanged={changed} />}
      </Container>

      {tabs.length > 1 && (
        <Paper elevation={3} sx={{ position: 'fixed', left: 0, right: 0, bottom: 0, pb: 'env(safe-area-inset-bottom)', zIndex: 10 }}>
          <BottomNavigation value={tab} onChange={(_, v: Tab) => { setTab(v); if (v === 'activity') setRefreshKey((k) => k + 1) }}
            showLabels sx={{ height: 72 }}>
            {tabs.map(([v, label, icon]) => <BottomNavigationAction key={v} value={v} label={label} icon={icon} />)}
          </BottomNavigation>
        </Paper>
      )}

      <Snackbar open={!!toast} autoHideDuration={toast?.error ? 6000 : 2500} onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }} sx={{ bottom: { xs: 90 } }}>
        {toast ? <Alert severity={toast.error ? 'error' : 'success'} variant="filled" onClose={() => setToast(null)}
          sx={{ width: '100%' }}>{toast.msg}</Alert> : undefined}
      </Snackbar>
    </Notify.Provider>
  )
}
