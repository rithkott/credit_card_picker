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
| spark-miles | capital-one | drafted |
| spark-miles-select | capital-one | drafted |
| venture-x-business | capital-one | drafted |
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

## 22B queue — Bank of America

business-advantage-customized-cash, business-advantage-unlimited-cash,
business-advantage-travel-rewards, alaska-airlines-business

## 22B queue — Citi

costco-anywhere-business, aadvantage-business (Citi exited some business
products — confirm active lineup during curation)

## 22B queue — Fleet (vertical tier, decide inclusion at 22B start)

wex-fleet, fuelman-fleet, shell-fleet-plus

## Notes

- Exact ids/lineups are provisional — curation confirms what is actually open
  to new applicants and prunes discontinued products (availability field).
- Every draft follows `docs/ai-conversion-protocol.md` + the business addendum
  (to be written at 22B start), lands `confidence: low` with NEEDS-human-
  verification markers unless checked against issuer terms in-session.
