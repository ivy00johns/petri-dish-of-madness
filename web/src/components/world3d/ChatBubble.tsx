/**
 * ChatBubble — a transient rounded speech bubble billboarded above an actor.
 * Spawned for each new agent_speech event; fades out after a few seconds.
 * Private whispers render dimmer/smaller. Long text is truncated upstream.
 */

import { useEffect, useState } from 'react';
import { Html } from '@react-three/drei';

export interface BubbleData {
  /** Unique id (event seq). */
  id: number;
  /** Animated world position of the speaking agent at spawn time. */
  text: string;
  private: boolean;
}

interface ChatBubbleProps {
  text: string;
  isPrivate: boolean;
  /** Vertical stacking offset (0 = closest to head). */
  stackIndex: number;
  /** Height above the agent's head where bubbles begin. */
  baseY: number;
}

const LIFETIME_MS = 5000;
const FADE_MS = 700;

export function ChatBubble({ text, isPrivate, stackIndex, baseY }: ChatBubbleProps) {
  const [opacity, setOpacity] = useState(0);

  useEffect(() => {
    // pop in
    const inT = window.setTimeout(() => setOpacity(1), 10);
    // start fade near end of life
    const fadeT = window.setTimeout(() => setOpacity(0), LIFETIME_MS - FADE_MS);
    return () => {
      window.clearTimeout(inT);
      window.clearTimeout(fadeT);
    };
  }, []);

  const y = baseY + stackIndex * 0.7;

  return (
    <Html
      position={[0, y, 0]}
      center
      distanceFactor={14}
      zIndexRange={[40, 0]}
      style={{ pointerEvents: 'none' }}
    >
      <div
        style={{
          transform: `scale(${isPrivate ? 0.85 : 1})`,
          opacity,
          transition: `opacity ${FADE_MS}ms ease, transform 180ms ease`,
          // An explicit width is required: under <Html center distanceFactor>
          // the containing block shrink-fits to min-content, which (with
          // word breaking) collapses the bubble to one character per line.
          width: 168,
          boxSizing: 'border-box',
          padding: '6px 10px',
          borderRadius: 14,
          background: isPrivate ? 'rgba(60,48,40,0.82)' : 'rgba(255,250,240,0.96)',
          color: isPrivate ? '#f0e6da' : '#3a2f25',
          fontFamily: '"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif',
          fontSize: 12,
          lineHeight: 1.3,
          fontStyle: isPrivate ? 'italic' : 'normal',
          boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
          border: isPrivate ? '1px solid rgba(255,255,255,0.15)' : '1px solid rgba(0,0,0,0.08)',
          whiteSpace: 'normal',
          overflowWrap: 'break-word',
          textAlign: 'center',
          userSelect: 'none',
        }}
      >
        {isPrivate && <span style={{ opacity: 0.7, marginRight: 4 }}>whisper</span>}
        {text}
      </div>
    </Html>
  );
}
