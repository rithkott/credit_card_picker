/** Parse-session queue semantics (concurrent uploads): files added while an
 * earlier drop is still uploading join the same session, and dedupe plus the
 * file cap span every drop. The network layer is mocked — parseStatement is
 * the only seam these tests care about. */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../../api')>()
  return { ...mod, parseStatement: vi.fn() }
})

import { parseStatement } from '../../api'
import { createParseSession, parseFiles, MAX_FILES } from './index'
import type { WireParsedFile } from './types'

const parseStatementMock = vi.mocked(parseStatement)

function wireFile(name: string): WireParsedFile {
  return {
    summary: {
      name, format: 'csv', txns: 1, rejected_rows: 0,
      range_start: '2026-01-01', range_end: '2026-01-31',
    },
    matches: [{
      date: '2026-01-05', amount_cents: 1234, descriptor: 'DELTA AIR 006',
      kind: 'purchase', line: 2, usage_key: 'delta', usage_label: 'Delta',
    }],
  }
}

/** Distinct bytes per name so the SHA-256 dedupe doesn't collapse them. */
const input = (name: string) => ({ name, bytes: new TextEncoder().encode(name) })

beforeEach(() => {
  parseStatementMock.mockReset()
  parseStatementMock.mockImplementation(async (name) => wireFile(name))
})

describe('createParseSession', () => {
  it('files added mid-parse join the running batch', async () => {
    let releaseFirst!: () => void
    const firstUploadStarted = new Promise<void>((started) => {
      parseStatementMock.mockImplementationOnce((name) => {
        started()
        return new Promise((resolve) => {
          releaseFirst = () => resolve(wireFile(name))
        })
      })
    })

    const progress: Array<[number, number]> = []
    const session = createParseSession((done, total) => progress.push([done, total]))
    session.add([input('a.csv')])
    await firstUploadStarted
    session.add([input('b.csv')]) // a.csv still in flight
    releaseFirst()

    const batch = await session.settled()
    expect(batch.files.map((f) => f.summary.name)).toEqual(['a.csv', 'b.csv'])
    expect(batch.errors).toEqual([])
    // The progress total grew from 1 to 2 once the second drop landed.
    expect(progress[0]).toEqual([0, 1])
    expect(progress.at(-1)).toEqual([2, 2])
  })

  it('dedupes byte-identical files across separate drops', async () => {
    const session = createParseSession()
    session.add([input('jan.csv')])
    await session.settled()
    session.add([{ name: 'jan-again.csv', bytes: new TextEncoder().encode('jan.csv') }])

    const batch = await session.settled()
    expect(batch.files.map((f) => f.summary.name)).toEqual(['jan.csv'])
    expect(batch.duplicates).toEqual(['jan-again.csv'])
    expect(parseStatementMock).toHaveBeenCalledTimes(1)
  })

  it('enforces the file cap across the whole session', async () => {
    const session = createParseSession()
    session.add(Array.from({ length: MAX_FILES }, (_, i) => input(`f${i}.csv`)))
    await session.settled()
    session.add([input('overflow.csv')])

    const batch = await session.settled()
    expect(batch.files).toHaveLength(MAX_FILES)
    expect(batch.errors).toEqual([{
      name: 'overflow.csv',
      message: `Batch limit is ${MAX_FILES} files — overflow.csv was not read.`,
    }])
  })

  it('settled() resolves immediately on an idle session', async () => {
    const session = createParseSession()
    expect(await session.settled()).toEqual({ files: [], errors: [], duplicates: [] })
  })
})

describe('parseFiles', () => {
  it('keeps the one-shot contract: parse a fixed batch and report progress', async () => {
    const progress: Array<[number, number, string | undefined]> = []
    const batch = await parseFiles(
      [input('a.csv'), input('b.csv')],
      (done, total, current) => progress.push([done, total, current]))

    expect(batch.files.map((f) => f.summary.name)).toEqual(['a.csv', 'b.csv'])
    expect(progress).toEqual([
      [0, 2, 'a.csv'], [1, 2, 'b.csv'], [2, 2, undefined],
    ])
  })

  it('turns a failed upload into a per-file error without killing the batch', async () => {
    parseStatementMock.mockImplementation(async (name) => {
      if (name === 'bad.csv') throw new TypeError('network down')
      return wireFile(name)
    })

    const batch = await parseFiles([input('bad.csv'), input('good.csv')])
    expect(batch.files.map((f) => f.summary.name)).toEqual(['good.csv'])
    expect(batch.errors).toEqual([{
      name: 'bad.csv',
      message: 'bad.csv: upload failed — check your connection and retry.',
    }])
  })
})
