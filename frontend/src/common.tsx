import { createContext, useContext } from 'react'
import Computer from '@mui/icons-material/Computer'
import DevicesOther from '@mui/icons-material/DevicesOther'
import Laptop from '@mui/icons-material/Laptop'
import Smartphone from '@mui/icons-material/Smartphone'
import Speaker from '@mui/icons-material/Speaker'
import SportsEsports from '@mui/icons-material/SportsEsports'
import TabletAndroid from '@mui/icons-material/TabletAndroid'
import Tv from '@mui/icons-material/Tv'
import Watch from '@mui/icons-material/Watch'
import Box from '@mui/material/Box'
import { useTheme } from '@mui/material/styles'
import type { SvgIconProps } from '@mui/material/SvgIcon'
import type { TrafficPoint } from './api'

export const KINDS: { value: string; label: string }[] = [
  { value: 'phone', label: 'Phone' },
  { value: 'tablet', label: 'Tablet' },
  { value: 'laptop', label: 'Laptop' },
  { value: 'computer', label: 'Computer' },
  { value: 'tv', label: 'TV / streaming' },
  { value: 'console', label: 'Game console' },
  { value: 'watch', label: 'Watch' },
  { value: 'speaker', label: 'Speaker' },
  { value: 'other', label: 'Other' },
]

export function KindIcon({ kind, ...p }: { kind: string | null } & SvgIconProps) {
  switch (kind) {
    case 'phone': return <Smartphone {...p} />
    case 'tablet': return <TabletAndroid {...p} />
    case 'laptop': return <Laptop {...p} />
    case 'computer': return <Computer {...p} />
    case 'tv': return <Tv {...p} />
    case 'console': return <SportsEsports {...p} />
    case 'watch': return <Watch {...p} />
    case 'speaker': return <Speaker {...p} />
    default: return <DevicesOther {...p} />
  }
}

/** Snackbar hook shared by every screen. */
export const Notify = createContext<(msg: string, error?: boolean) => void>(() => {})
export const useNotify = () => useContext(Notify)

/** Tiny bar chart of bytes per poll over the requested window. */
export function Sparkline({ points, from, to, height = 48 }: {
  points: TrafficPoint[]; from: number; to: number; height?: number
}) {
  const theme = useTheme()
  const buckets = 48
  const span = (to - from) / buckets
  const sums = new Array(buckets).fill(0)
  for (const p of points) {
    const i = Math.min(buckets - 1, Math.max(0, Math.floor((p.ts - from) / span)))
    sums[i] += p.bytes
  }
  const max = Math.max(...sums, 1)
  return (
    <Box component="svg" viewBox={`0 0 ${buckets * 4} ${height}`} preserveAspectRatio="none"
      sx={{ width: '100%', height, display: 'block' }} role="img" aria-label="Traffic over time">
      {sums.map((v, i) => {
        const h = v ? Math.max(2, (v / max) * (height - 2)) : 0
        return <rect key={i} x={i * 4} y={height - h} width={3} height={h} rx={1}
          fill={theme.palette.primary.main} opacity={0.85} />
      })}
      <line x1={0} x2={buckets * 4} y1={height - 0.5} y2={height - 0.5} stroke={theme.palette.divider} />
    </Box>
  )
}
