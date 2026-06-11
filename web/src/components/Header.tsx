/**
 * Header — top bar with title, tick counter, connection status, mock mode badge.
 */

import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

interface HeaderProps {
  tick: number;
  day: number;
  running: boolean;
  connected: boolean;
  mockMode: boolean;
}

export function Header({ tick, day, running, connected, mockMode }: HeaderProps) {
  const [tickFlash, setTickFlash] = useState(false);
  const location = useLocation();
  const onInspector = location.pathname === '/inspector';

  useEffect(() => {
    setTickFlash(true);
    const t = setTimeout(() => setTickFlash(false), 150);
    return () => clearTimeout(t);
  }, [tick]);

  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-lab-border bg-lab-surface shrink-0">
      {/* Title — the page's single h1 (EM-082 heading hierarchy). */}
      <div className="flex items-center gap-3">
        <h1 className="m-0 flex items-center gap-1 font-mono text-sm font-bold tracking-widest uppercase">
          <span className="text-lab-acid">PETRI DISH</span>
          <span className="text-lab-text">OF MADNESS</span>
        </h1>
        <span className="font-mono text-[10px] text-lab-dim border border-lab-border px-1 py-px hidden sm:inline">
          CHAOS LAB v1
        </span>

        {/* Route toggle — 3D live world ⇄ 2D analysis annex. */}
        <Link
          to={onInspector ? '/' : '/inspector'}
          className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-border-bright text-lab-text bg-lab-chrome hover:bg-lab-border hover:text-lab-acid transition-colors rounded-sm no-underline"
          aria-label={onInspector ? 'Back to the live 3D world' : 'Open the Inspector analysis annex'}
          title={onInspector ? 'Back to the live world' : 'Open the Inspector (analysis)'}
        >
          {onInspector ? '← Live' : 'Inspector'}
        </Link>
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

      {/* Right — support link + status badges */}
      <div className="flex items-center gap-2">
        {/* Buy-me-a-coffee — opens in a new tab so it never leaves the live
            world; height-capped to sit in the compact header row. */}
        <a
          href="https://www.buymeacoffee.com/john00ivyz"
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 leading-none"
          title="Buy me a coffee"
          aria-label="Buy me a coffee"
        >
          <img
            src="https://img.buymeacoffee.com/button-api/?text=Buy me a coffee&emoji=&slug=john00ivyz&button_colour=5F7FFF&font_colour=ffffff&font_family=Cookie&outline_colour=000000&coffee_colour=FFDD00"
            alt="Buy me a coffee"
            className="h-6 w-auto block"
          />
        </a>
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
