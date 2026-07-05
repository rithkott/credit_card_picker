/** Statement file-format sniffing (plan 09).
 *
 * Content-based, extension as tiebreak only: banks are sloppy with download
 * names (.qfx files that are XML, .csv attachments served as .txt).
 */

export type StatementFormat = 'pdf' | 'ofx' | 'csv' | 'unknown'

export function detectFormat(bytes: Uint8Array, name: string): StatementFormat {
  // TextDecoder consumes a leading UTF-8 BOM by default.
  const head = new TextDecoder('utf-8', { fatal: false })
    .decode(bytes.subarray(0, 2048))

  if (head.startsWith('%PDF-')) return 'pdf'

  const upper = head.toUpperCase()
  if (upper.includes('OFXHEADER') || upper.includes('<OFX>')) return 'ofx'

  const ext = name.toLowerCase().split('.').pop() ?? ''
  if (ext === 'ofx' || ext === 'qfx') return 'ofx'

  // CSV: a plausible delimited header line (no NUL bytes, has a comma or tab
  // in the first non-empty line).
  if (!head.includes('\0')) {
    const firstLine = head.split(/\r?\n/).find((l) => l.trim() !== '')
    if (firstLine && (firstLine.includes(',') || firstLine.includes('\t'))) return 'csv'
    if (ext === 'csv') return 'csv'
  }
  return 'unknown'
}
