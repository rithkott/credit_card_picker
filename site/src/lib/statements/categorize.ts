/** Deterministic transaction categorization (plan 09, commit 4/5).
 *
 * Rules come from GET /api/config (statement_import — data/meta/
 * category-rules.yaml + statement-descriptors.yaml); nothing is embedded
 * here. Layered matching per transaction, first hit wins:
 *
 *   1. descriptor patterns -> descriptor_categories bridge; the same hit also
 *      tallies a merchant carve-out (merchants.yaml keys) and a confirmed-
 *      usage suggestion (usage-questions items). Aggregator-prefix keys strip
 *      the matched prefix and re-run layers 1-2 on the remainder; explicitly
 *      unmapped keys (venmo, bilt_rent) surface as labeled review groups.
 *   2. generic keyword stems
 *   3. the issuer's own CSV category column
 *   4. MCC / OFX SIC ranges
 *
 * Within a layer the LONGEST pattern wins; identical patterns shared by two
 * descriptor keys (APPLE.COM/BILL) break ties by ascending key so matching is
 * order-independent and deterministic.
 */

import type { ConfigMerchant, StatementImportRules, UsageItem } from '../../types'
import type { NormalizedTxn } from './types'

export interface Match {
  category: string | null
  merchantKey?: string
  usageKey?: string
  /** Set on any layer-1 hit; carries the registry label for labeled
   * uncategorized groups (explicitly-unmapped keys). */
  descriptorKey?: string
  descriptorLabel?: string
  layer: 1 | 2 | 3 | 4 | null
}

interface Pattern { pattern: string; key: string }

export interface Matcher {
  descriptorPatterns: Pattern[]           // length desc, key asc
  keywordPatterns: Pattern[]              // key = category; length desc
  bridge: Record<string, string>
  prefixes: Record<string, { fallback_category?: string }>
  issuerCategories: Record<string, string>
  mcc: { from: number; to: number; category: string }[]
  merchantByKey: Map<string, ConfigMerchant>
  usageLabels: Map<string, string>
  descriptorLabels: Map<string, string>
}

const byLengthThenKey = (a: Pattern, b: Pattern) =>
  b.pattern.length - a.pattern.length || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0)

export function compileRules(
  rules: StatementImportRules,
  merchants: ConfigMerchant[],
  usageItems: UsageItem[],
): Matcher {
  const descriptorPatterns: Pattern[] = rules.descriptors
    .flatMap((d) => d.patterns.map((p) => ({ pattern: p.toUpperCase(), key: d.key })))
    .sort(byLengthThenKey)
  const keywordPatterns: Pattern[] = Object.entries(rules.keywords)
    .flatMap(([category, patterns]) =>
      patterns.map((p) => ({ pattern: p.toUpperCase(), key: category })))
    .sort(byLengthThenKey)
  return {
    descriptorPatterns,
    keywordPatterns,
    bridge: rules.descriptor_categories,
    prefixes: rules.aggregator_prefixes,
    issuerCategories: rules.issuer_categories,
    mcc: rules.mcc,
    merchantByKey: new Map(merchants.map((m) => [m.key, m])),
    usageLabels: new Map(usageItems.map((i) => [i.key, i.label])),
    descriptorLabels: new Map(rules.descriptors.map((d) => [d.key, d.label])),
  }
}

export function normalizeDescriptor(descriptor: string): string {
  return descriptor.toUpperCase().replace(/\s+/g, ' ').trim()
}

function findPattern(patterns: Pattern[], upper: string): Pattern | undefined {
  return patterns.find((p) => upper.includes(p.pattern))
}

/** Layers 1-2 on a descriptor string; depth guards prefix recursion. */
function matchDescriptor(m: Matcher, upper: string, depth: number): Match {
  const hit = findPattern(m.descriptorPatterns, upper)
  if (hit) {
    const key = hit.key
    const attach = {
      descriptorKey: key,
      descriptorLabel: m.descriptorLabels.get(key),
      ...(m.merchantByKey.has(key) ? { merchantKey: key } : {}),
      ...(m.usageLabels.has(key) ? { usageKey: key } : {}),
    }
    const bridged = m.bridge[key]
    if (bridged !== undefined) return { category: bridged, layer: 1, ...attach }

    const prefix = m.prefixes[key]
    if (prefix && depth === 0) {
      // Strip the matched prefix; the real merchant follows it.
      const at = upper.indexOf(hit.pattern)
      const remainder = upper.slice(at + hit.pattern.length).trim()
      if (remainder !== '') {
        const inner = matchDescriptor(m, remainder, 1)
        if (inner.category !== null) return inner
      }
      if (prefix.fallback_category !== undefined) {
        return { category: prefix.fallback_category, layer: 1, ...attach }
      }
      return { category: null, layer: null } // unknown merchant behind prefix
    }
    // Explicitly unmapped (or prefix at depth): labeled group, user's call.
    return { category: null, layer: null, ...attach }
  }

  const kw = findPattern(m.keywordPatterns, upper)
  if (kw) return { category: kw.key, layer: 2 }
  return { category: null, layer: null }
}

export function matchTxn(m: Matcher, t: NormalizedTxn): Match {
  const upper = normalizeDescriptor(t.descriptor)
  const direct = matchDescriptor(m, upper, 0)
  if (direct.category !== null || direct.descriptorKey !== undefined) return direct

  if (t.issuerCategory !== undefined) {
    const cat = m.issuerCategories[t.issuerCategory]
    if (cat !== undefined) return { category: cat, layer: 3 }
  }
  if (t.mcc !== undefined) {
    const range = m.mcc.find((r) => t.mcc! >= r.from && t.mcc! <= r.to)
    if (range) return { category: range.category, layer: 4 }
  }
  return { category: null, layer: null }
}

/** Group key for uncategorized transactions: strip store numbers, dates, and
 * punctuation noise so "KWIK-E-MART #442 SPRINGFIELD" and "#187" group. */
export function descriptorStem(descriptor: string): string {
  const cleaned = normalizeDescriptor(descriptor)
    .replace(/[#*]?\d[\d\-/.]*/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  const stem = cleaned.split(' ').slice(0, 3).join(' ')
  return stem !== '' ? stem : normalizeDescriptor(descriptor)
}
