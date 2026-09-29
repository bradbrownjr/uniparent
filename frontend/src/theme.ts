import { createTheme } from '@mui/material/styles'

// Material 3–style tonal palette (teal primary) on MUI, light and dark from the phone's setting.
export function makeTheme(dark: boolean) {
  return createTheme({
    palette: dark
      ? {
          mode: 'dark',
          primary: { main: '#4fd8de', contrastText: '#003739' },
          secondary: { main: '#b1ccce' },
          error: { main: '#ffb4ab', contrastText: '#690005' },
          success: { main: '#7fdb8f', contrastText: '#00391a' },
          background: { default: '#0f1415', paper: '#1b2122' },
        }
      : {
          mode: 'light',
          primary: { main: '#00696d', contrastText: '#ffffff' },
          secondary: { main: '#4a6364' },
          error: { main: '#ba1a1a' },
          success: { main: '#1d6c34' },
          background: { default: '#f4fafa', paper: '#ffffff' },
        },
    shape: { borderRadius: 16 },
    typography: {
      fontFamily: 'Roboto, system-ui, sans-serif',
      button: { textTransform: 'none', fontWeight: 600 },
    },
    components: {
      MuiCard: { defaultProps: { elevation: 0 }, styleOverrides: { root: { borderRadius: 24 } } },
      MuiButton: { styleOverrides: { root: { borderRadius: 999 } } },
      MuiChip: { styleOverrides: { root: { borderRadius: 8 } } },
      MuiDialog: { styleOverrides: { paper: { borderRadius: 28 } } },
      MuiAppBar: { defaultProps: { elevation: 0, color: 'transparent' } },
    },
  })
}
