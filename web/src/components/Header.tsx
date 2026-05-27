/**
 * Header — top bar with title, tick counter, connection status, mock mode badge.
 */

import { useEffect, useState } from 'react';

interface HeaderProps {
  tick: number;
  day: number;
  running: boolean;
  connected: boolean;
  mockMode: boolean;
}

export function Header({ tick, day, running, connected, mockMode }: HeaderProps) {
  const [tickFlash, setTickFlash] = useState(false);

  useEffect(() => {
    setTickFlash(true);
    const t = setTimeout(() => setTickFlash(false), 150);
    return () => clearTimeout(t);
  }, [tick]);

  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-lab-border bg-lab-surface shrink-0">
      {/* Title */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          <span className="font-mono text-sm font-bold tracking-widest text-lab-acid uppercase">
            EMERGENCE
          </span>
          <span className="font-mono text-sm font-bold tracking-widest text-lab-text uppercase">
            MADNESS
          </span>
        </div>
        <span className="font-mono text-[10px] text-lab-dim border border-lab-border px-1 py-px hidden sm:inline">
          CHAOS LAB v1
        </span>
      </div>

      {/* Center — tick / day counter */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[10px] text-lab-muted">TICK</span>
          <span
            className={`font-mono text-sm font-bold tabular-nums transition-colors duration-150 ${
              tickFlash ? 'text-lab-acid' : 'text-lab-text'
            }`}
          >
            {String(tick).padStart(4, '0')}
          </span>
        </div>
        <span className="text-lab-border">|</span>
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[10px] text-lab-muted">DAY</span>
          <span className="font-mono text-sm font-bold tabular-nums text-lab-text">
            {day}
          </span>
        </div>
        <span className="text-lab-border">|</span>
        {/* Running indicator */}
        <div className="flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full ${running ? 'animate-pulse' : ''}`}
            style={{ backgroundColor: running ? '#27ae60' : '#ff9900' }}
          />
          <span
            className="font-mono text-[10px] font-semibold"
            style={{ color: running ? '#27ae60' : '#ff9900' }}
          >
            {running ? 'RUNNING' : 'PAUSED'}
          </span>
        </div>
      </div>

      {/* Right — status badges */}
      <div className="flex items-center gap-2">
        {mockMode && (
          <span className="font-mono text-[10px] font-bold px-2 py-1 border border-lab-acid text-lab-acid bg-lab-acid/10">
            MOCK
          </span>
        )}
        <div className="flex items-center gap-1.5">
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: connected ? '#27ae60' : '#ff3333' }}
          />
          <span
            className="font-mono text-[10px]"
            style={{ color: connected ? '#27ae60' : '#ff3333' }}
          >
            {connected ? 'LIVE' : 'DISCONNECTED'}
          </span>
        </div>
      </div>
    </header>
  );
}
