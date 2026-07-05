/** PDF statement parsing — ships in plan 09 commit 3/5. This stub keeps the
 * lazy `import('./pdf')` in index.ts compiling until then; PDF uploads get a
 * clear per-file error instead of a broken parse. */

import { StatementParseError } from './types'
import type { ParsedFile } from './types'

export async function parsePdf(_bytes: Uint8Array, file: string): Promise<ParsedFile> {
  throw new StatementParseError(`${file}: PDF statements aren't supported yet — download the CSV export instead.`)
}
