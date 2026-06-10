/**
 * ModelBoundary — the COMPLETE Wave C fallback invariant for GLB content
 * (contract rule 7) in one wrapper:
 *
 *   • while a model streams, <Suspense> shows the procedural fallback;
 *   • if the load FAILS (404, network, malformed GLB), drei's useGLTF cache
 *     re-throws the rejection during render — a bare <Suspense> does NOT
 *     catch that, it would unmount the whole canvas tree (verified: blocking
 *     /models/** blacked out the app). This class boundary catches it and
 *     pins the procedural fallback permanently for this building.
 *
 * Generic React (works inside the R3F reconciler), so Villager/Critter (C5)
 * can wrap their capsule fallbacks with it too.
 *
 * Usage:
 *   <ModelBoundary fallback={<ProceduralThing/>}>
 *     <Model spec={spec} ... />
 *   </ModelBoundary>
 */

import { Component, Suspense, type ReactNode } from 'react';

interface ModelBoundaryProps {
  /** The procedural stand-in: rendered while loading AND forever on failure. */
  fallback: ReactNode;
  children: ReactNode;
}

interface ModelBoundaryState {
  failed: boolean;
}

export class ModelBoundary extends Component<ModelBoundaryProps, ModelBoundaryState> {
  state: ModelBoundaryState = { failed: false };

  static getDerivedStateFromError(): ModelBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    // One warn per failing instance; the scene stays whole on the procedural
    // mesh, so this is informational, not fatal.
    console.warn('[world3d] GLB failed to load — procedural fallback pinned:', error);
  }

  render(): ReactNode {
    if (this.state.failed) return this.props.fallback;
    return <Suspense fallback={this.props.fallback}>{this.props.children}</Suspense>;
  }
}
