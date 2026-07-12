/** Display names for issuer slugs. Presentation-only (the slug itself is the
 * data); anything not listed falls back to title-cased slug. Shared by the
 * Data sources tab and Manual mode's card grid. */
const ISSUER_LABELS: Record<string, string> = {
  'amex': 'American Express',
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
