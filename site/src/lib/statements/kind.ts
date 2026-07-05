/** Transaction-kind classification (plan 09).
 *
 * Card statements mix real spend with payments, fees, interest, and cash
 * advances; only purchases/refunds may reach categorization, or a $2,000
 * "PAYMENT THANK YOU" would inflate a spend bucket. Classification layers:
 * explicit type columns (CSV Type, OFX TRNTYPE) first, then descriptor
 * patterns — a DEBIT row reading "ANNUAL FEE" is still a fee.
 */

import type { TxnKind } from './types'

const PAYMENT_PATTERNS = [
  'PAYMENT THANK YOU', 'PAYMENT - THANK YOU', 'THANK YOU FOR YOUR PAYMENT',
  'AUTOPAY', 'AUTO-PAY', 'AUTOMATIC PAYMENT', 'ONLINE PAYMENT', 'ACH PAYMENT',
  'MOBILE PAYMENT', 'PAYMENT RECEIVED', 'ELECTRONIC PAYMENT', 'E-PAYMENT',
  'DIRECTPAY', 'ONLINE TRANSFER TO', 'PAYMENT FROM CHK', 'PYMT',
]
const INTEREST_PATTERNS = [
  'INTEREST CHARGE', 'PURCHASE INTEREST', 'INTEREST CHARGED', 'FINANCE CHARGE',
]
const FEE_PATTERNS = [
  'ANNUAL FEE', 'ANNUAL MEMBERSHIP FEE', 'MEMBERSHIP FEE', 'LATE FEE',
  'LATE PAYMENT FEE', 'FOREIGN TRANSACTION FEE', 'RETURNED PAYMENT FEE',
  'CASH ADVANCE FEE', 'OVERLIMIT FEE',
]
const TRANSFER_PATTERNS = ['BALANCE TRANSFER', 'CASH ADVANCE']

/** CSV Type-column values (Chase/Apple-style), lowercased. */
const CSV_TYPE_KINDS: Record<string, TxnKind> = {
  sale: 'purchase',
  purchase: 'purchase',
  return: 'refund',
  refund: 'refund',
  payment: 'payment',
  fee: 'fee',
  interest: 'interest',
  adjustment: 'refund',
}

/** OFX <TRNTYPE> values. DEBIT/CREDIT/POS stay 'purchase' here — refund vs
 * purchase is decided by the normalized sign, and payment-looking CREDITs are
 * caught by the descriptor patterns below. */
const OFX_TYPE_KINDS: Record<string, TxnKind> = {
  int: 'interest',
  fee: 'fee',
  srvchg: 'fee',
  xfer: 'transfer',
  payment: 'payment',
}

export function classifyKind(
  descriptor: string,
  hints?: { csvType?: string; ofxType?: string },
): TxnKind {
  const upper = descriptor.toUpperCase()
  // Descriptor patterns win over generic DEBIT/CREDIT typing but lose to an
  // explicit non-purchase column type (an issuer's own "Fee" flag is truth).
  const explicit = hints?.csvType
    ? CSV_TYPE_KINDS[hints.csvType.trim().toLowerCase()]
    : hints?.ofxType
      ? OFX_TYPE_KINDS[hints.ofxType.trim().toLowerCase()]
      : undefined
  if (explicit && explicit !== 'purchase' && explicit !== 'refund') return explicit

  if (upper.trim() === 'PAYMENT') return 'payment' // Bilt prints bare "PAYMENT"
  if (INTEREST_PATTERNS.some((p) => upper.includes(p))) return 'interest'
  if (FEE_PATTERNS.some((p) => upper.includes(p))) return 'fee'
  if (TRANSFER_PATTERNS.some((p) => upper.includes(p))) return 'transfer'
  if (PAYMENT_PATTERNS.some((p) => upper.includes(p))) return 'payment'
  return explicit ?? 'purchase'
}

/** After sign normalization (spend positive), a negative purchase is a refund. */
export function refineRefund(kind: TxnKind, amountCents: number): TxnKind {
  return kind === 'purchase' && amountCents < 0 ? 'refund' : kind
}
