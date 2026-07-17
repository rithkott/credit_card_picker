# Business card backlog (plan 22)

Tracking source of truth for the BUSINESS corpus (~70 cards, exhaustive per the
plan 22 scope decision): every card file under `data/business/cards/` must be
listed here (validator-warned), and every unshipped card below is 22B curation
work. Status: `seeded` (22A skeleton, low confidence) → `drafted` (22B, offer
file converted) → `verified` (human-checked against issuer terms).

## Seeded (22A)

| id | issuer | status |
|---|---|---|
| ink-business-cash | chase | seeded |
| ink-business-preferred | chase | seeded |
| business-gold | amex | seeded |
| business-platinum | amex | seeded |
| spark-cash-plus | capital-one | seeded |
| ramp-corporate-card | ramp | seeded |

## Drafted (22B batch 1)

| id | issuer | status |
|---|---|---|
| ink-business-unlimited | chase | drafted |
| ink-business-premier | chase | drafted |
| blue-business-plus | amex | drafted |
| blue-business-cash | amex | drafted |
| triple-cash-rewards-business | us-bank | drafted |
| signify-business-cash | wells-fargo | drafted |
| brex-card | brex | drafted |
| bill-divvy-card | bill | drafted |

## Drafted (22B batch 2 — Chase co-brands + CSR for Business)

| id | issuer | status |
|---|---|---|
| sapphire-reserve-for-business | chase | drafted |
| united-business | chase | drafted |
| united-club-business | chase | drafted |
| southwest-premier-business | chase | drafted |
| southwest-performance-business | chase | drafted |
| world-of-hyatt-business | chase | drafted |
| ihg-premier-business | chase | drafted |

## Drafted (22B batch 3 — Capital One + US Bank)

| id | issuer | status |
|---|---|---|
| spark-cash-select | capital-one | drafted |
| spark-miles | capital-one | discontinued (2026-07-17 lineup check) |
| spark-miles-select | capital-one | discontinued (2026-07-17 lineup check) |
| venture-x-business | capital-one | drafted |
| spark-cash | capital-one | drafted (added + verified 2026-07-17) |
| venture-business | capital-one | drafted (added + verified 2026-07-17) |
| venture-one-business | capital-one | drafted (added + verified 2026-07-17) |
| spark-classic | capital-one | drafted |
| business-altitude-connect | us-bank | drafted |
| business-altitude-power | us-bank | drafted |
| business-leverage | us-bank | drafted |

## Drafted (22B batch 4 — Amex remainder)

| id | issuer | status |
|---|---|---|
| business-green | amex | drafted |
| plum-card | amex | drafted |
| delta-skymiles-gold-business | amex | drafted |
| delta-skymiles-platinum-business | amex | drafted |
| delta-skymiles-reserve-business | amex | drafted |
| hilton-honors-business | amex | drafted |
| marriott-bonvoy-business | amex | drafted |
| amazon-business-prime | amex | drafted |

## Drafted (22B batch 5 — BofA + Citi)

| id | issuer | status |
|---|---|---|
| business-advantage-customized-cash | bank-of-america | drafted |
| business-advantage-unlimited-cash | bank-of-america | drafted |
| business-advantage-travel-rewards | bank-of-america | drafted |
| alaska-airlines-business | bank-of-america | drafted |
| costco-anywhere-business | citi | drafted |
| aadvantage-business | citi | drafted |

## Verification pass 1 (2026-07-17, official-page WebFetch sweep)

Core figures (earn structure / fees / SUBs / employee cards) checked against
LIVE official pages; per-file details in each card's sources + verified_by.

- **Verified → confidence: medium**: all 11 Chase cards partially-to-fully
  (compare page; earn structures of co-brands still curator-mapped), Spark
  Cash Plus/Cash Select/Classic, Venture X Business (already matched), US Bank
  Triple Cash/Altitude Connect/Altitude Power (fee amounts redacted on page,
  still inferred), Wells Signify (exact match), BofA Customized/Unlimited/
  Travel Rewards, Amex Blue Business Plus/Cash (via NerdWallet — Amex pages
  are JS shells).
- **Corrections applied**: United Business $99→$150, SW Premier $99→$149,
  SW Performance $199→$299, Spark Classic 1.5%→1%, Altitude Connect gained its
  real $150k combined 4X cap + portal 5X lines, most SUBs updated to current
  elevated offers.
- **Lineup changes found**: Capital One replaced the Spark Miles line with
  Venture Business cards → spark-miles + spark-miles-select marked
  discontinued; NEW cards added: spark-cash, venture-business,
  venture-one-business (all verified vs capitalone.com).
- **Still low confidence (source pages unreachable/JS-shell)**: Amex Business
  Gold/Platinum (earlier NerdWallet verify stands), Green, Plum, Delta ×3,
  Hilton, Marriott, Amazon Prime; Citi ×2 (product renamed → Citi/AAdvantage
  Business World Elite; numbers placeholder on page); Alaska Business; Ramp
  cashback rate; Brex/Divvy reward details.
- **New product spotted, queued**: US Bank Business Shield (5% Travel Center,
  insurance-focused) — add in a future batch.

## Verification pass 2 (browser, 2026-07-17)

- **New products spotted, queued**:
  - Amex **Graphite Business Cash Unlimited** — $295 AF, unlimited 2% cash
    (Reward Dollars), 5% portal flights/prepaid hotels, $1,500/$50k/6mo SUB,
    Pay Over Time. On the americanexpress.com lineup 2026-07-17.
  - Amazon **Prime Business Card** (successor co-brand; Mastercard,
    Chase-serviced per cardholder reviews) — 5% Amazon/Amazon
    Business/AWS/Whole Foods up to $150k/yr then 1%; 2% on top-3 non-Amazon
    categories from a fixed menu (up to $150k/yr); +1% with Amazon Day
    Delivery (6% total); 1% base; personalized offer seen: $100 statement
    credit after $3k/3mo. Replaces the discontinued Amazon Business Prime
    Amex.
- **Lineup changes found**: Amex Plum Card and Amazon Business Prime Amex
  marked `discontinued` (absent from lineups; Plum URL 500s, Amazon page now
  markets the successor).

## Fleet cards — EXCLUDED from V1 (decision 2026-07-17)

wex-fleet, fuelman-fleet, shell-fleet-plus: fleet cards rebate in cents PER
GALLON (volume-based), not percent-per-dollar — the earn-rate schema cannot
model them deterministically without a gallons input. Documented as out of
scope; revisit if a per-unit-rebate mechanic is ever added.

## Notes

- Exact ids/lineups are provisional — curation confirms what is actually open
  to new applicants and prunes discontinued products (availability field).
- Every draft follows `docs/ai-conversion-protocol.md` + the business addendum
  (to be written at 22B start), lands `confidence: low` with NEEDS-human-
  verification markers unless checked against issuer terms in-session.
