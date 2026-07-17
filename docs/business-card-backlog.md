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

## 22B queue — Chase

ink-business-unlimited, ink-business-premier, sapphire-reserve-for-business,
united-business, united-club-business, southwest-performance-business,
southwest-premier-business, world-of-hyatt-business, ihg-premier-business

## 22B queue — Amex

blue-business-plus, blue-business-cash, business-green, plum-card,
delta-skymiles-gold-business, delta-skymiles-platinum-business,
delta-skymiles-reserve-business, hilton-honors-business,
marriott-bonvoy-business, amazon-business-prime (co-brand TBD by issuer dir)

## 22B queue — Capital One

spark-cash-select, spark-miles, spark-miles-select, venture-x-business,
spark-classic

## 22B queue — US Bank

triple-cash-rewards-business, business-altitude-connect,
business-altitude-power, business-leverage

## 22B queue — Bank of America

business-advantage-customized-cash, business-advantage-unlimited-cash,
business-advantage-travel-rewards, alaska-airlines-business

## 22B queue — Citi

costco-anywhere-business, aadvantage-business (Citi exited some business
products — confirm active lineup during curation)

## 22B queue — Wells Fargo

signify-business-cash

## 22B queue — Fintech corporate charge

brex-card (brex), bill-divvy-card (bill)

## 22B queue — Fleet (vertical tier, decide inclusion at 22B start)

wex-fleet, fuelman-fleet, shell-fleet-plus

## Notes

- Exact ids/lineups are provisional — curation confirms what is actually open
  to new applicants and prunes discontinued products (availability field).
- Every draft follows `docs/ai-conversion-protocol.md` + the business addendum
  (to be written at 22B start), lands `confidence: low` with NEEDS-human-
  verification markers unless checked against issuer terms in-session.
