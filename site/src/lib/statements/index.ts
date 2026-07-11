/** Statement-import entry point (plan 09; server-side parsing since plan 12):
 * upload each file to POST /api/statements/parse with hard limits and
 * whole-file dedupe. Operates on bytes (not File objects) so it is testable;
 * the upload component reads Files into ArrayBuffers and calls parseFiles.
 * One bad file never kills the batch — it becomes a per-file error the UI
 * shows as a chip.
 *
 * The SHA-256 dedupe stays client-side ON PURPOSE: a byte-identical duplicate
 * is skipped before it is ever uploaded.
 */

import { ApiError, parseStatement } from '../../api'
import { StatementParseError } from './types'
import type { FileError, ParsedFile, WireParsedFile } from './types'

/** 4 MB tracks the server's cap (itself under Vercel's 4.5 MB request-body
 * limit); the pre-check here means an oversize file fails fast with a local
 * message instead of a doomed upload. */
export const MAX_FILE_BYTES = 4 * 1024 * 1024
export const MAX_FILES = 50 // two cards x 24 monthly PDFs must fit in one batch
export const MAX_TXNS_TOTAL = 50_000

export interface FileInput { name: string; bytes: Uint8Array }

/** Per-file progress: `done` files finished out of `total`, `current` is the
 * file being uploaded next (undefined once the batch is complete). */
export type ParseProgress = (done: number, total: number, current?: string) => void

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

/** Wire (snake_case) -> browser (camelCase) conversion. */
export function fromWire(wire: WireParsedFile): ParsedFile {
  const s = wire.summary
  const t = s.statement_totals
  return {
    summary: {
      name: s.name,
      format: s.format,
      txns: s.txns,
      rejectedRows: s.rejected_rows,
      rangeStart: s.range_start,
      rangeEnd: s.range_end,
      ...(t !== undefined ? {
        statementTotals: {
          ...(t.purchases_cents !== undefined ? { purchasesCents: t.purchases_cents } : {}),
          ...(t.payments_and_credits_cents !== undefined
            ? { paymentsAndCreditsCents: t.payments_and_credits_cents } : {}),
          ...(t.fees_cents !== undefined ? { feesCents: t.fees_cents } : {}),
          ...(t.interest_cents !== undefined ? { interestCents: t.interest_cents } : {}),
        },
      } : {}),
      ...(s.period_count !== undefined ? { periodCount: s.period_count } : {}),
      ...(s.extraction !== undefined ? { extraction: s.extraction } : {}),
      ...(s.column_inference !== undefined ? { columnInference: s.column_inference } : {}),
    },
    txns: wire.txns.map((w) => ({
      dateISO: w.date,
      amountCents: w.amount_cents,
      descriptor: w.descriptor,
      kind: w.kind,
      match: {
        category: w.match.category,
        layer: w.match.layer,
        method: w.match.method,
        ...(w.match.confidence !== undefined ? { confidence: w.match.confidence } : {}),
        ...(w.match.merchant_key !== undefined ? { merchantKey: w.match.merchant_key } : {}),
        ...(w.match.usage_key !== undefined ? { usageKey: w.match.usage_key } : {}),
        ...(w.match.descriptor_key !== undefined ? { descriptorKey: w.match.descriptor_key } : {}),
        ...(w.match.descriptor_label !== undefined
          ? { descriptorLabel: w.match.descriptor_label } : {}),
        stem: w.match.stem,
      },
      source: { file: s.name, line: w.line },
    })),
  }
}

/** Upload one file, retrying ONCE on transient failures (network error or
 * 5xx). 4xx responses are real per-file answers and never retried. */
async function uploadOnce(name: string, bytes: Uint8Array): Promise<WireParsedFile> {
  try {
    return await parseStatement(name, bytes)
  } catch (e) {
    const transient = !(e instanceof ApiError) || e.status >= 500
    if (!transient) throw e
    return await parseStatement(name, bytes)
  }
}

export async function parseFiles(
  inputs: FileInput[], onProgress?: ParseProgress,
): Promise<ParseBatchResult> {
  const files: ParsedFile[] = []
  const errors: FileError[] = []
  const duplicates: string[] = []
  const seenHashes = new Set<string>()
  let txnsTotal = 0

  const batch = inputs.slice(0, MAX_FILES)
  let done = 0
  for (const input of batch) {
    onProgress?.(done, batch.length, input.name)
    try {
      if (input.bytes.byteLength > MAX_FILE_BYTES) {
        throw new StatementParseError(
          `${input.name} is larger than ${MAX_FILE_BYTES / 1024 / 1024} MB — ` +
          `download the CSV export from your issuer instead.`)
      }
      const hash = await sha256Hex(input.bytes)
      if (seenHashes.has(hash)) {
        duplicates.push(input.name)
        continue
      }
      seenHashes.add(hash)

      const parsed = fromWire(await uploadOnce(input.name, input.bytes))

      txnsTotal += parsed.txns.length
      if (txnsTotal > MAX_TXNS_TOTAL) {
        throw new StatementParseError(
          `Transaction limit reached (${MAX_TXNS_TOTAL.toLocaleString('en-US')}) — ` +
          `import fewer files at once.`)
      }
      files.push(parsed)
    } catch (e) {
      if (e instanceof ApiError) {
        errors.push({ name: input.name, message: e.message,
                      ...(e.code !== undefined ? { code: e.code } : {}) })
      } else if (e instanceof StatementParseError) {
        errors.push({ name: input.name, message: e.message })
      } else {
        errors.push({ name: input.name,
                      message: `${input.name}: upload failed — check your connection and retry.` })
      }
    } finally {
      done += 1
    }
  }
  onProgress?.(done, batch.length)
  for (const skipped of inputs.slice(MAX_FILES)) {
    errors.push({ name: skipped.name, message: `Batch limit is ${MAX_FILES} files — ${skipped.name} was not read.` })
  }
  return { files, errors, duplicates }
}
