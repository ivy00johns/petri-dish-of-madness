/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"IBM Plex Mono"', 'monospace'],
        display: ['"IBM Plex Mono"', 'monospace'],
        ui: ['"IBM Plex Sans Condensed"', '"IBM Plex Sans"', 'sans-serif'],
      },
      colors: {
        lab: {
          bg: '#0a0a0b',
          surface: '#111114',
          chrome: '#1a1a20',
          border: '#252530',
          'border-bright': '#3a3a48',
          text: '#e8e8f0',
          muted: '#5a5a72',
          dim: '#3a3a50',
          acid: '#c8ff00',
          'acid-dim': '#8ab300',
          danger: '#ff3333',
          warn: '#ff9900',
          // God-panel accent (W7 spawn) — a violet that reads "creator mode".
          god: '#7b6cf6',
          'god-bright': '#a99bff',
        }
      },
      animation: {
        'slide-in': 'slideIn 0.2s ease-out',
        'pulse-ring': 'pulseRing 2s ease-in-out infinite',
        'flash': 'flash 0.3s ease-out',
        'tick-flash': 'tickFlash 0.15s ease-out',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateX(-8px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        pulseRing: {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        flash: {
          '0%': { backgroundColor: 'rgba(200, 255, 0, 0.15)' },
          '100%': { backgroundColor: 'transparent' },
        },
        tickFlash: {
          '0%': { color: '#c8ff00' },
          '100%': { color: 'inherit' },
        },
      },
    },
  },
  plugins: [],
}
