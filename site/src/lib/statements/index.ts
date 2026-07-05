/** Statement-import entry point (plan 09): dispatch files to their format
 * parser with hard limits and whole-file dedupe. Operates on bytes (not File
 * objects) so it is testable in node; the upload component reads Files into
 * ArrayBuffers and calls parseFiles. One bad file never kills the batch —
 * it becomes a per-file error the UI shows as a chip.
 */

import { detectFormat } from './detect'
import { parseCsv } from './csv'
import { parseOfx } from './ofx'
import { StatementParseError } from './types'
import type { FileError, ParsedFile } from './types'

export const MAX_FILE_BYTES = 10 * 1024 * 1024
export const MAX_FILES = 50 // two cards x 24 monthly PDFs must fit in one batch
export const MAX_TXNS_TOTAL = 50_000

export interface FileInput { name: string; bytes: Uint8Array }

export interface ParseBatchResult {
  files: ParsedFile[]
  errors: FileError[]
  /** Names of byte-identical files skipped as duplicates. */
  duplicates: string[]
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
  const digest = await crypto.subtle.digest('SHA-256', buf)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export async function parseFiles(inputs: FileInput[]): Promise<ParseBatchResult> {
  const files: ParsedFile[] = []
  const errors: FileError[] = []
  const duplicates: string[] = []
  const seenHashes = new Set<string>()
  let txnsTotal = 0

  for (const input of inputs.slice(0, MAX_FILES)) {
    try {
      if (input.bytes.byteLength > MAX_FILE_BYTES) {
        throw new StatementParseError(
          `${input.name} is larger than ${MAX_FILE_BYTES / 1024 / 1024} MB.`)
      }
      const hash = await sha256Hex(input.bytes)
      if (seenHashes.has(hash)) {
        duplicates.push(input.name)
        continue
      }
      seenHashes.add(hash)

      const format = detectFormat(input.bytes, input.name)
      let parsed: ParsedFile
      if (format === 'csv') {
        parsed = parseCsv(new TextDecoder().decode(input.bytes), input.name)
      } else if (format === 'ofx') {
        parsed = parseOfx(new TextDecoder().decode(input.bytes), input.name)
      } else if (format === 'pdf') {
        // Lazy chunk: pdf.js only loads when a PDF is actually uploaded.
        const { parsePdf } = await import('./pdf')
        parsed = await parsePdf(input.bytes, input.name)
      } else {
        throw new StatementParseError(
          `${input.name}: unrecognized format — upload a CSV, OFX/QFX, or PDF ` +
          `statement export.`)
      }

      txnsTotal += parsed.txns.length
      if (txnsTotal > MAX_TXNS_TOTAL) {
        throw new StatementParseError(
          `Transaction limit reached (${MAX_TXNS_TOTAL.toLocaleString('en-US')}) — ` +
          `import fewer files at once.`)
      }
      files.push(parsed)
    } catch (e) {
      const message = e instanceof StatementParseError
        ? e.message
        : `${input.name}: unexpected parse failure.`
      errors.push({ name: input.name, message })
    }
  }
  for (const skipped of inputs.slice(MAX_FILES)) {
    errors.push({ name: skipped.name, message: `Batch limit is ${MAX_FILES} files — ${skipped.name} was not read.` })
  }
  return { files, errors, duplicates }
}
