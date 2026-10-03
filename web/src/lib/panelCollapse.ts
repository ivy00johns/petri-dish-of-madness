/**
 * Shared collapse-preference storage for the left-column panels (feed primacy,
 * 2026-10-03 live feedback). Panels persist their own collapsed flag, but the
 * pre-fix components also persisted '0' (expanded) ON MOUNT — so every browser
 * that ever loaded the old UI carries stale expanded pins that would defeat
 * the new default-collapsed behavior forever (key versioning alone can't help:
 * a hot-reload re-persists the old state under the new key).
 *
 * The marker key makes the new defaults a ONE-TIME migration: the first load
 * after this change ignores every persisted value and starts collapsed; from
 * then on (marker set by the first save) each panel's persisted preference is
 * respected. An explicit expand persists '0' and sticks — the user wins after
 * the first visit, exactly as intended.
 */

/** One-time migration marker for the 2026-10-03 default-collapsed rollout. */
const DEFAULTS_MARKER = 'em.panelDefaults.v2';

/** Load a panel's collapsed flag, applying the one-time default migration. */
export function loadPanelCollapsed(key: string): boolean {
  try {
    if (localStorage.getItem(DEFAULTS_MARKER) !== '1') {
      // Migration pass: ignore stale pins (including a poisoned '0' written by
      // the pre-fix persist-on-mount) and apply the new default — collapsed.
      return true;
    }
    return localStorage.getItem(key) !== '0';
  } catch {
    return true;
  }
}

/** Persist a panel's collapsed flag and mark the migration as done. */
export function savePanelCollapsed(key: string, collapsed: boolean): void {
  try {
    localStorage.setItem(key, collapsed ? '1' : '0');
    localStorage.setItem(DEFAULTS_MARKER, '1');
  } catch {
    /* storage unavailable (private mode etc.) — preference just won't stick */
  }
}
