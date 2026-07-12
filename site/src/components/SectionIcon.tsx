import type { ReactNode } from 'react'

/** Decorative glass icon that sits in the left gutter of a section.block.
 * Each home-page section passes a name; the section also carries the
 * `has-icon` class so the block reserves the gutter (see global.css). Icons
 * are inline stroke SVGs (lucide-style) so they inherit the accent color and
 * need no asset pipeline. Purely decorative — aria-hidden. */
export type SectionIconName =
  | 'document'
  | 'rewards'
  | 'travel'
  | 'home'
  | 'spend'
  | 'usage'
  | 'user'

const svgProps = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

const PATHS: Record<Exclude<SectionIconName, 'travel'>, ReactNode> = {
  document: (
    <>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M9 13h6" />
      <path d="M9 17h5" />
    </>
  ),
  rewards: (
    <path d="M12 2.6l2.75 5.57 6.15.9-4.45 4.34 1.05 6.12L12 16.6l-5.5 2.93 1.05-6.12L3.1 9.07l6.15-.9z" />
  ),
  home: (
    <>
      <path d="m3 9.5 9-7 9 7V20a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M9 22V12h6v10" />
    </>
  ),
  spend: (
    <>
      <rect x="2" y="5" width="20" height="14" rx="2.5" />
      <path d="M2 10h20" />
      <path d="M6 15h4" />
    </>
  ),
  usage: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  user: (
    <>
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </>
  ),
}

// Plane + building diorama for the airlines/hotels loyalty block.
const PLANE = (
  <path d="M17.8 19.2 16 11l3.5-3.5a2.12 2.12 0 0 0-3-3L13 8 4.8 6.2a1 1 0 0 0-.9 1.7l4.1 3.1-2.3 2.3-2-.5a1 1 0 0 0-.9 1.6L5 18l1.6 2.4a1 1 0 0 0 1.6-.1l2.3-2 3.1 4.1a1 1 0 0 0 1.7-.9z" />
)
const BUILDING = (
  <>
    <path d="M6 22V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v17" />
    <path d="M17 10h2a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4" />
    <path d="M10 8h1M13 8h0M10 12h1M13 12h0M10 16h1M13 16h0" />
  </>
)

export function SectionIcon({ name }: { name: SectionIconName }) {
  if (name === 'travel') {
    return (
      <div className="block-icon duo" aria-hidden="true">
        <svg className="duo-a" {...svgProps}>{PLANE}</svg>
        <svg className="duo-b" {...svgProps}>{BUILDING}</svg>
      </div>
    )
  }
  return (
    <div className="block-icon" aria-hidden="true">
      <svg width="27" height="27" {...svgProps}>{PATHS[name]}</svg>
    </div>
  )
}
