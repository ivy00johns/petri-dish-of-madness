/**
 * Test-only JSX intrinsics.
 *
 * R3F render tests (jsdom) mock the <Model> GLB wrapper with a queryable
 * placeholder tag — react-dom renders an unknown lowercase tag as a custom
 * element, so a test can assert WHICH GLB url / tint mounted without loading
 * bytes (and a distinct tag avoids colliding with the real `<group>` queries).
 * Declare those stub tags so the project build (`tsc -b`) accepts them; vitest
 * (esbuild) never type-checks, which is why these slipped past `tsc --noEmit`.
 *
 * Test infrastructure only — never used in application code.
 */
import 'react';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      // PlacedProps.test.tsx — stub for the mocked prop <Model> (carries data-url).
      propGlbStub: any;
      // Structure.skin.test.tsx — stub for the mocked building <Model> (carries data-tint).
      modelStub: any;
    }
  }
}
