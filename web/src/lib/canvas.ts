/**
 * Canvas drawing utilities for the world map.
 */

import type { Place, Agent, PlaceKind } from '../types';

export const CANVAS_LOGICAL = 1000; // logical coordinate space

// Place kind → icon char and color
export const PLACE_KIND_CONFIG: Record<PlaceKind, { icon: string; color: string; label: string }> = {
  work:       { icon: '⚙',  color: '#f39c12', label: 'WORK'  },
  home:       { icon: '⌂',  color: '#27ae60', label: 'HOME'  },
  social:     { icon: '◉',  color: '#3498db', label: 'SOCIAL'},
  governance: { icon: '⚖',  color: '#9b59b6', label: 'GOV'  },
  wild:       { icon: '♣',  color: '#1abc9c', label: 'WILD'  },
};

// Scale logical [0..1000] to canvas pixel
export function scaleCoord(val: number, canvasSize: number): number {
  return (val / CANVAS_LOGICAL) * canvasSize;
}

export function drawPlace(
  ctx: CanvasRenderingContext2D,
  place: Place,
  cx: number,
  cy: number,
  radius: number,
) {
  const cfg = PLACE_KIND_CONFIG[place.kind];

  // Outer glow ring
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, radius + 4, 0, Math.PI * 2);
  ctx.strokeStyle = cfg.color + '40'; // 25% opacity
  ctx.lineWidth = 2;
  ctx.stroke();

  // Place node body
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = '#111114';
  ctx.fill();
  ctx.strokeStyle = cfg.color;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Place name label
  ctx.font = `bold 10px "IBM Plex Mono", monospace`;
  ctx.fillStyle = cfg.color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText(place.name.toUpperCase(), cx, cy + radius + 6);

  ctx.restore();
}

export function drawAgent(
  ctx: CanvasRenderingContext2D,
  agent: Agent,
  cx: number,
  cy: number,
  idx: number,
  totalAtPlace: number,
) {
  const AGENT_R = 14;
  const color = agent.profile_color ?? '#888888';

  // Cluster offset — arrange agents in a circle around the place node
  const spreadRadius = totalAtPlace > 1 ? 28 : 0;
  const angle = totalAtPlace > 1 ? (idx / totalAtPlace) * Math.PI * 2 - Math.PI / 2 : 0;
  const ax = cx + Math.cos(angle) * spreadRadius;
  const ay = cy + Math.sin(angle) * spreadRadius;

  ctx.save();

  if (!agent.alive) {
    ctx.globalAlpha = 0.25;
    ctx.filter = 'saturate(0)';
  }

  // Energy ring (arc from top, clockwise)
  const energyAngle = (agent.energy / 100) * Math.PI * 2;
  ctx.beginPath();
  ctx.arc(ax, ay, AGENT_R + 3, -Math.PI / 2, -Math.PI / 2 + energyAngle);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.lineCap = 'round';
  ctx.stroke();

  // Energy ring background (empty)
  ctx.beginPath();
  ctx.arc(ax, ay, AGENT_R + 3, -Math.PI / 2 + energyAngle, -Math.PI / 2 + Math.PI * 2);
  ctx.strokeStyle = '#252530';
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // Agent body circle
  ctx.beginPath();
  ctx.arc(ax, ay, AGENT_R, 0, Math.PI * 2);
  ctx.fillStyle = color + '30'; // 19% opacity bg
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Initials
  const initials = agent.name.slice(0, 2).toUpperCase();
  ctx.font = `600 9px "IBM Plex Mono", monospace`;
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(initials, ax, ay);

  // Credits pip (bottom-right corner)
  if (agent.credits > 0) {
    ctx.beginPath();
    ctx.arc(ax + AGENT_R - 2, ay + AGENT_R - 2, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#c8ff00';
    ctx.fill();

    ctx.font = `bold 6px "IBM Plex Mono", monospace`;
    ctx.fillStyle = '#0a0a0b';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const label = agent.credits > 99 ? '99+' : String(agent.credits);
    ctx.fillText(label, ax + AGENT_R - 2, ay + AGENT_R - 2);
  }

  ctx.restore();
}

export function drawGrid(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
) {
  ctx.save();
  ctx.strokeStyle = '#1a1a20';
  ctx.lineWidth = 0.5;

  const step = width / 10;
  for (let x = 0; x <= width; x += step) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y <= height; y += step) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  ctx.restore();
}

// Draw a transit animation line between two places
export function drawTransit(
  ctx: CanvasRenderingContext2D,
  fromX: number, fromY: number,
  toX: number, toY: number,
  color: string,
  progress: number, // 0..1
) {
  const cx = fromX + (toX - fromX) * progress;
  const cy = fromY + (toY - fromY) * progress;

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(fromX, fromY);
  ctx.lineTo(cx, cy);
  ctx.strokeStyle = color + '60';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 5]);
  ctx.stroke();
  ctx.restore();
}
