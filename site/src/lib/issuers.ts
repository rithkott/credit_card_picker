/** Display names for issuer slugs. Presentation-only (the slug itself is the
 * data); anything not listed falls back to title-cased slug. Shared by the
 * Data sources tab and Manual mode's card grid. */
const ISSUER_LABELS: Record<string, string> = {
  'amex': 'American Express',
  'cardless': 'Bilt',
  'bank-of-america': 'Bank of America',
  'capital-one': 'Capital One',
  'goldman-sachs': 'Goldman Sachs',
  'navy-federal': 'Navy Federal',
  'penfed': 'PenFed',
  'sofi': 'SoFi',
  'td-bank': 'TD Bank',
  'wells-fargo': 'Wells Fargo',
  'us-bank': 'U.S. Bank',
  'hsbc': 'HSBC',
  'usaa': 'USAA',
  'bmo': 'BMO',
  'pnc': 'PNC',
}

export function issuerLabel(slug: string): string {
  if (ISSUER_LABELS[slug]) return ISSUER_LABELS[slug]
  return slug.split('-').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ')
}

/** Search-only nicknames per issuer slug so common shorthand finds the issuer
 * even when it isn't a substring of the display label (e.g. "amex" isn't in
 * "American Express", "bofa" isn't in "Bank of America"). Presentation stays
 * canonical via ISSUER_LABELS; this map is consulted only by the card search. */
const ISSUER_ALIASES: Record<string, string[]> = {
  'amex': ['amex'],
  'bank-of-america': ['bofa', 'boa', 'bank of america'],
  'capital-one': ['cap one', 'capone', 'c1'],
  'wells-fargo': ['wells', 'wf'],
  'us-bank': ['us bank', 'usbank'],
  'navy-federal': ['nfcu'],
  'penfed': ['pentagon federal'],
}

/** True when query `q` (already lowercased/trimmed) matches an issuer nickname. */
export function issuerMatchesAlias(slug: string, q: string): boolean {
  if (!q) return false
  return (ISSUER_ALIASES[slug] ?? []).some((a) => a.includes(q))
}
