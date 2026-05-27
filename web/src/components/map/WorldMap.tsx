/**
 * WorldMap — 2D canvas rendering of places and agents.
 */

import { useRef, useEffect, useCallback } from 'react';
import type { WorldState } from '../../types';
import { drawPlace, drawAgent, drawGrid, scaleCoord } from '../../lib/canvas';

interface WorldMapProps {
  world: WorldState | null;
}

export function WorldMap({ world }: WorldMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameRef = useRef<number>(0);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const W = container.clientWidth;
    const H = container.clientHeight;

    if (canvas.width !== W || canvas.height !== H) {
      canvas.width = W;
      canvas.height = H;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0a0a0b';
    ctx.fillRect(0, 0, W, H);

    // Grid
    drawGrid(ctx, W, H);

    if (!world) {
      // No-data placeholder
      ctx.font = '12px "IBM Plex Mono", monospace';
      ctx.fillStyle = '#3a3a50';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('AWAITING WORLD STATE…', W / 2, H / 2);
      return;
    }

    const { places, agents } = world;

    // Use the smaller dimension to scale, with padding
    const scaleX = (val: number) => scaleCoord(val, W * 0.88) + W * 0.06;
    const scaleY = (val: number) => scaleCoord(val, H * 0.88) + H * 0.06;

    // Build place position lookup
    const placePos: Record<string, { cx: number; cy: number }> = {};
    places.forEach(p => {
      placePos[p.id] = { cx: scaleX(p.x), cy: scaleY(p.y) };
    });

    // Draw connection lines between adjacent places (subtle)
    ctx.save();
    ctx.strokeStyle = '#252530';
    ctx.lineWidth = 0.5;
    ctx.setLineDash([3, 6]);
    const placeList = Object.values(placePos);
    for (let i = 0; i < placeList.length; i++) {
      for (let j = i + 1; j < placeList.length; j++) {
        const a = placeList[i], b = placeList[j];
        const dist = Math.hypot(a.cx - b.cx, a.cy - b.cy);
        if (dist < Math.min(W, H) * 0.45) {
          ctx.beginPath();
          ctx.moveTo(a.cx, a.cy);
          ctx.lineTo(b.cx, b.cy);
          ctx.stroke();
        }
      }
    }
    ctx.restore();

    // Group agents by location
    const agentsByPlace: Record<string, typeof agents> = {};
    agents.forEach(agent => {
      if (!agentsByPlace[agent.location]) agentsByPlace[agent.location] = [];
      agentsByPlace[agent.location].push(agent);
    });

    // Draw places
    const PLACE_R = Math.min(W, H) * 0.04;
    places.forEach(place => {
      const { cx, cy } = placePos[place.id];
      drawPlace(ctx, place, cx, cy, PLACE_R);
    });

    // Draw agents at their places
    Object.entries(agentsByPlace).forEach(([placeId, placeAgents]) => {
      const pos = placePos[placeId];
      if (!pos) return;
      placeAgents.forEach((agent, idx) => {
        drawAgent(ctx, agent, pos.cx, pos.cy, idx, placeAgents.length);
      });
    });

    // Tick counter overlay
    ctx.save();
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.fillStyle = '#3a3a50';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`TICK ${world.tick}  DAY ${world.day}`, W - 8, H - 6);
    ctx.restore();
  }, [world]);

  useEffect(() => {
    const frame = () => {
      render();
      animFrameRef.current = requestAnimationFrame(frame);
    };
    animFrameRef.current = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(animFrameRef.current);
    };
  }, [render]);

  // Handle resize
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      render();
    });
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }
    return () => observer.disconnect();
  }, [render]);

  return (
    <div ref={containerRef} className="relative w-full h-full bg-lab-bg">
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        aria-label="World map — agent positions"
      />
    </div>
  );
}
