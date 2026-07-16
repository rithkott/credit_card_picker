/** Compare path (plan 20): one identity color per portfolio, carried from the
 * tray dot/ring on the left through row chips to the catalog's ownership
 * rings and corner P-tags — you can always tell which portfolio a card
 * belongs to without scrolling back up. Indexed by portfolio position (max 4).
 * P1/P3 reuse the existing accent/warn palette; P2/P4 are the teal and slate
 * picked in the workbench handoff (design_handoff_compare_picker). */
export const PORT_COLORS = ['var(--p1)', 'var(--p2)', 'var(--p3)', 'var(--p4)'] as const
