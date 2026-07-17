# Plan 21 — Business Cards (3.0): Research Report

**Status: research complete — this document is the deliverable of the 3.0 research step. No build design here; that is the next plan.**

3.0 goal (user, 2026-07-16): a parallel business-card product — a new journey for CFOs, controllers, and financial analysts picking the best business-card lineup for company spend. New curated card corpus, new registries, business-tuned optimizer, near-replica UI with business framing; almost no shared assets with the consumer site.

## Method & verification status

Multi-angle web research (2026-07-16): 5 parallel search angles → 30 sources fetched → 122 falsifiable claims extracted with quotes → adversarial 3-vote verification. The verification stage was interrupted partway (session limit), so:

- **Verified (3-0 votes)**: Ink Business Cash $25k cap structure; Ink Business Preferred $150k cap structure; Chase free employee cards; Chase tiered Ink lineup; Amex employee-spend pooling to primary account.
- **Spot-checked against live pages (2026-07-17)**: Amex Business Gold ($375 fee, 4x top-two, $150k cap, 6 eligible categories); Amex Business Platinum ($895 fee, 2x on $5k+ purchases/business categories capped $2M/yr, 5x Amex Travel, $200 airline/$120 wireless/$150 Dell/$600 hotel credits); Ramp Plus $15/user/mo + platform fee; Brex Premium $12/user/mo.
- **Source-quoted, not independently re-verified**: everything else below. Raw claims + quotes: `~/.claude/plans/business-research-claims.jsonl` (kept outside repo). Sources listed in the appendix.

Anything that becomes card data later goes through the normal curation protocol (`docs/ai-conversion-protocol.md`) regardless of what this doc says — this report informs schema and product design, it is not card data.

---

## 1. Business spend categories ≠ consumer categories

Business cards bonus **operational spend**. Categories seen across the market, roughly by frequency:

| Category | Bonused by (examples) |
|---|---|
| Office supply stores | Ink Cash 5%, US Bank Triple Cash 3% |
| Internet/cable/phone (telecom, incl. wireless) | Ink Cash 5%, Ink Preferred 3x, Amex Business Gold 4x (wireless), US Bank 3% (cell service) |
| Shipping | Ink Preferred 3x, Amex Business Platinum 2x |
| Advertising (social media + search engines; Amex: online/TV/radio media) | Ink Preferred 3x, Amex Business Gold 4x |
| Software / cloud / electronics retailers | Amex Business Gold 4x, Amex Business Platinum 2x, Divvy 2x (recurring SaaS) |
| Construction materials & hardware suppliers | Amex Business Platinum 2x |
| Gas / EV charging (fleet fuel) | Ink Cash 2%, US Bank 3%, Amex Business Gold 4x |
| Dining | Ink Cash 2%, US Bank 3%, Divvy up to 7x, Amex Business Gold 4x |
| Travel (flights/hotels/other) | Ink Preferred 3x, Amex Business Platinum 5x (portal), co-brands |
| Transit | Amex Business Gold 4x |

Overlap with the consumer enum is only gas/dining/travel/transit. Groceries, streaming, drugstores, rent — the core consumer buckets — are irrelevant; advertising, shipping, SaaS, office supplies, telecom, construction materials are the business core.

Fleet cards (WEX, Fuelman, Shell Fleet) are a distinct vertical product line, sometimes underwritten on business credit via EIN — noted for completeness, likely out of corpus V1.

**Proposed business category enum (~14 buckets, to be finalized in build plan):** `advertising`, `shipping`, `software_saas`, `telecom`, `office_supplies`, `travel_flights`, `travel_hotels`, `travel_other`, `fuel_fleet`, `dining`, `transit`, `utilities`, `contractors_materials`, `wholesale`, `insurance_professional_services`, `other`. Cross-checked against the bonus tables above; final enum must be re-validated against the actual corpus during curation.

## 2. Spend caps are structural, not edge cases

The consumer dataset treats caps as occasional annotations. In business cards, **caps define the product tiering**:

| Card | Bonus | Cap | Post-cap |
|---|---|---|---|
| Ink Business Cash ($0) | 5% office supply + telecom; separate 2% gas + dining | $25,000/yr combined **per tier** | 1% |
| Amex Blue Business Cash ($0) | 2% everything | $50,000/yr | 1% |
| Ink Business Preferred ($95) | 3x travel/ads/shipping/telecom | $150,000/yr combined | 1x |
| Amex Business Gold ($375) | 4x top-two of 6 categories | $150,000/yr combined | 1x |
| Amex Business Platinum ($895) | 2x on 4 business categories AND any purchase ≥$5,000 | $2,000,000/yr | 1x |

Modeling consequences:

- **Combined caps across categories**: the current schema `cap` is per category-reward. Ink Cash's $25k spans office supply + telecom *together* (and a second $25k spans gas + dining). Needs a cap-group concept: several category_rewards sharing one annual pool.
- **Cap exhaustion drives portfolio math**: at $500k+ company spend, every capped card saturates; marginal value of a card = pre-cap rate on capped dollars + base rate on overflow. The optimizer must overflow post-cap spend to the next-best card in the portfolio — mechanically the existing cap logic does this, but at consumer scale caps rarely bind, at business scale they always do. Blended effective rate becomes the headline number.
- **Transaction-size-gated rates** (new mechanic): Amex Business Platinum 2x applies to *individual purchases ≥$5,000*; Ink Premier pays 2.5% on *purchases ≥$5,000* (2% otherwise). Deterministic modeling needs a profile input like "share of spend in $5k+ invoices" (or per-category average transaction size).
- **Top-N adaptive categories** (new mechanic, optimizer-friendly): Amex Business Gold 4x on top two of six eligible categories per cycle. Given a fixed spend profile this is deterministic: pick the user's two highest eligible categories.
- **No-pooling flags**: Ink Premier cash back cannot be combined with other Chase cards nor transferred to partners — pooling behavior is a per-card attribute, not per-program.

## 3. Employee cards — new first-class concept

- **Rewards pool centrally.** Employee-card spend earns to the primary business account at the card's normal rates (verified for Amex; consistent across Chase/Capital One/Wells Fargo/US Bank sources). For the optimizer: employee spend is just company spend.
- **Cost varies and belongs in the fee model**: free on Chase Ink, Capital One, Wells Fargo, US Bank, most others; Amex Business Gold $95/employee card; Amex Business Platinum $400/employee Platinum (both Amex cards also offer $0 "Employee Business Expense Cards" with lesser benefits). Amex allows up to 99 employee cards per account. → Profile needs an **employee-card count** input; card needs `employee_card_fee_usd` (and possibly a free-tier variant note).
- **Quirks**: US Bank Triple Cash excludes employee-card spend from signup-bonus spend requirements (bonus feasibility check must optionally exclude employee spend per card).
- **Liability**: company is liable for employee charges; employee personal credit unaffected. Amex limits are *soft* — tips, extended hotel stays can exceed them, and the account holder owes all charges regardless.
- **Controls are a feature axis, not a scoring axis** (V1): per-card limits (all mainstream issuers), merchant-category restrictions and real-time alerts (Amex, fintechs), pre-transaction policy enforcement (Ramp/Brex — controls enforced at the point of swipe). Model as benefit flags surfaced in UI, unscored.

## 4. Card tiers & underwriting — replaces the FICO axis

Four tiers in the market:

1. **SMB issuer cards** (Chase Ink, Amex Business, Capital One Spark, US Bank, Wells Fargo, BofA, Citi): SSN application + **personal guarantee**; underwritten on the owner's personal FICO (~670+ for Chase); sole proprietors qualify without an EIN. Personal liability; most don't report routine activity to personal credit (see §5). Revolving credit or charge hybrids.
2. **Premium SMB charge-style** (Spark Cash Plus, Venture X Business, Amex charge lineage): no preset spending limit, designed to be paid in full; still personally guaranteed. Spark Cash Plus refunds its $150 fee at $150k+ annual spend (volume-conditional fee — another small mechanic).
3. **Fintech corporate charge** (Ramp, Brex, BILL Divvy): **EIN-anchored, no personal guarantee, no personal credit check**; underwritten on business bank balance / revenue / funding — Ramp ≥$25k linked US business bank balance; Divvy >$20k cash balance; Brex ~$50k+ for funded startups, or >$500k annual revenue, or equity funding; US incorporation + physical US address required (no PO boxes). Charge cards: pay in full monthly (or daily). **No card fees; monetized as per-seat SaaS** — Ramp Plus $15/user/mo + platform fee (free tier exists), Brex Premium $12/user/mo (Essentials free). Rewards: Brex variable points up to 8x select categories; Ramp flat cashback; Divvy tiered multipliers (up to 7x restaurants / 5x hotels / 2x recurring SaaS) at no annual fee. Unlimited free physical/virtual cards.
4. **Traditional corporate programs** (JPM, SVB, BofA commercial): C/S-corp only, roughly $4M+ revenue and 2–3 years operating history, sometimes 15+ cardholders minimum; **corporate liability**; negotiated **volume-tiered rebates** (illustrative: 1% first $500k, 1.5% next $500k, 2% above $1M — issuer-negotiated, not public rate cards); full-pay monthly; credit lines >$100k. **Not deterministically curatable** — rates are negotiated per company.

**Scope decision (user, 2026-07-16): corpus = tiers 1–3.** SMB issuer cards fully curated; fintech corporate charge (Brex/Ramp/Divvy) included with per-seat pricing modeled. Traditional corporate programs documented in the UI/docs as "beyond this tool — negotiate with your bank" but not curated.

**Approval axis redesign** (replaces `approval.credit_tier` / `TIER_ORDER` / FICO): eligibility for a business card is a function of —
- entity type (sole prop / LLC / S-corp / C-corp),
- owner personal FICO (tier-1/2 cards only),
- willingness to sign a personal guarantee (gates tier 1/2 vs tier 3),
- business bank cash balance (gates Ramp/Brex/Divvy),
- annual revenue and/or funding status (gates Brex tiers),
- US incorporation/EIN.

These become business-profile inputs; `filter_cards` equivalent screens on them. Exact schema shape is build-plan territory.

## 5. Personal↔business interactions — FULL model in scope (user decision 2026-07-16)

The optimizer will model cross-product rules, with the user's personal holdings + application history as profile inputs:

- **Point pooling / cross-product gateways**: Business UR points combine with personal Chase cards under one login (or to a household member / company owner per Chase terms). Cash-back-tier Inks (Cash/Unlimited) earn UR that becomes *transferable* (and 1.5cpp-class value on CSR) only when the holder also has a premium card — personal Sapphire or Ink Preferred. The existing `unlocks_transfers` gateway mechanic extends naturally, but the gateway can live on a *personal* card the business user already holds → profile needs "premium personal cards held" (Sapphire Preferred/Reserve, Amex personal Platinum/Gold). Amex MR pools similarly across personal+business under one MR account.
- **5/24 (Chase)**: applicants with ≥5 personal card openings in 24 months are denied most Chase cards *including business cards*; but Chase/Amex/Citi business cards, once opened, do **not** add to the count (they don't report to personal credit). Capital One (most), Discover, TD business cards **do** count (report personally) — with Venture X Business and Spark Cash Plus as exceptions that don't. → Profile input: current 5/24 count. Optimizer: exclude Chase cards when ≥5/24; annotate which recommendations affect future 5/24 standing.
- **Amex 5-credit-card limit**: max 5 Amex *credit* cards as primary, shared across personal+business; charge-lineage cards (Platinum/Gold/Green, personal + business) are exempt. → Profile input: count of Amex credit cards held. Portfolio constraint: personal Amex credit cards + recommended business Amex credit cards ≤ 5.
- **Velocity rules** (recorded as data; sequencing advice is a UI concern, not a hard optimizer constraint): Capital One ~1 card/6 months across personal+business; Citi 1 business card/95 days; Chase ~2 accounts/30 days by reports, 3–4 month spacing recommended. Amex once-per-lifetime welcome-bonus rule affects year-1 valuations for previously-held products.

This is the deepest divergence from the consumer optimizer: portfolio feasibility now depends on *application-rule state*, not just card attributes. The build plan must decide how far constraints go into `search` (hard exclusions: 5/24, Amex limit) vs. presentation (velocity sequencing hints).

## 6. What CFOs optimize for that consumers don't

- **Float / working capital**: the card extends days-payable-outstanding by 20–55 days beyond invoice arrival (SVB offers up to 55-day cycles vs the usual 30). Finance teams treat float as a first-class return stream; companies on net-30 pay in ~15 days on average, leaving working capital unused. → Candidate scored-or-reported metric: portfolio "average float days" (grace period + cycle length per card). V1 could report it without scoring it.
- **Volume rebates**: corporate-tier economics are flat/tiered hard rebates (~1% average) rather than category multipliers — relevant context for docs, mostly outside the curated corpus (tier 4).
- **Expense-management / ERP integration**: native QuickBooks/NetSuite/Xero/Sage Intacct connections (Ramp, Brex) vs partner integrations (Amex) vs statement exports. Straight-through reconciliation is a selection criterion CFOs rank alongside rewards; check/ACH-style manual reconciliation is the anti-pattern. → Per-card feature flags (`integrations: [quickbooks, netsuite, xero, sage_intacct]`), unscored V1, filterable/surfaced in UI.
- **Virtual cards + real-time controls**: fintechs enforce policy pre-swipe and auto-lock on violations; traditional issuers do card-level limits with post-hoc review. >2/3 of growth-company CFOs planned to expand virtual-card use (Visa research). → Benefit flags.
- **Fee structure asymmetry**: annual fee per card (traditional) vs $/user/month SaaS (fintech). Comparing Ramp Plus vs Amex fairly requires a **seats** input: annualized fintech cost = seats × monthly × 12 (+ platform fee), vs annual fee + employee-card fees on traditional cards. Free tiers (Ramp/Brex $0) make tier-3 cards strictly fee-free at base tier — the paid tiers buy software, not card economics, so V1 could model fintech cards at $0 with a note.
- **Statement-credit ecosystems**: Amex Business Platinum's fee offset ($200 airline, $600 hotel, $150 Dell, $120 wireless…) mirrors the consumer credits model — existing `credits[]` + `confirmed_usage` machinery carries over, with business-usage questions (Do you buy Dell? Fly for business?).
- **Out of optimizer scope (document only)**: early-payment discounts (2%/10 net 30) competing with card float; interest/APR optimization (business cards ~21.5% average APR; charge cards moot); 1099/tax bookkeeping.

## 7. Company spend profiles by size/industry

Weakest-covered topic (verification stage died before profile-specific sources were fetched). What we have: small businesses account for >35% of US B2B commercial-card spend (~$500B) — the market is real and SMB-weighted.

Archetype sketches (drafted from category structure, **needs a follow-up research pass before they become presets**):

- **DTC/e-commerce**: advertising-dominant (often 30–60% of card-able spend), shipping heavy, SaaS moderate → Ink Preferred's ad/shipping 3x saturates its $150k cap quickly.
- **SaaS/startup**: software/cloud + advertising + travel; low physical spend → Amex Business Gold top-two adapts well; Brex/Ramp natural fit (funded, EIN, controls).
- **Trades/construction**: construction materials + fuel + telecom → Business Platinum's construction 2x ($5k+ invoices common), fleet cards adjacent.
- **Restaurant**: wholesale/food supply (largely un-bonused), utilities, delivery-platform fees → flat-rate cards dominate.
- **Agency/professional services**: travel + dining + advertising (pass-through) + SaaS.

Product implication: business spend entry should be **annual, large-denomination, category-first** (CFOs know their GL categories; no statement-parsing dependency), with presets per archetype as an on-ramp — analogous to the consumer wizard but sourced from the business enum.

## 8. Multi-card portfolios for businesses

- **SMB tier: multi-card is normal and issuer-encouraged.** Chase's Ink line is explicitly tiered for stacking: $0 flat 1.5% (Unlimited) + $0 capped 5% (Cash) + $95 3x points (Preferred) + co-brands (United/Southwest/Hyatt/IHG), with cash-back Inks pooling into UR through the premium card. The consumer optimizer's portfolio-construction thesis transfers directly — arguably *better*, since caps bind and overflow demands multiple cards.
- **Fintech/corporate tier: usually one program.** A company runs one Ramp/Brex as its spend platform, possibly alongside 1–2 issuer cards for category bonuses. Portfolio semantics differ: fintech program = platform choice; issuer cards = yield optimization on top.
- **Constraints to encode as data**: Amex 5-card limit, 5/24 gate, Ink Premier no-pooling, velocity rules (§5), per-card employee-card fees (§3).
- `max_cards` range likely stays small (1–5) but the *composition* question changes: "platform + satellites" vs consumer "flat + category stack."

---

## Implications summary (input to the build-design plan)

**New schema concepts** (business schema, forked from consumer): cap groups (combined cross-category annual caps); transaction-size-gated rates; top-N adaptive category rewards; `employee_card_fee_usd` + employee-card count interaction; per-seat SaaS pricing block (fintech tier); no-pooling flag; business approval block (entity type, PG required, min cash balance, min revenue, FICO floor where applicable); integration/controls benefit flags; issuer application-rule metadata (counts-toward-5/24, adds-to-5/24, Amex-credit-limit membership, velocity class).

**New profile inputs**: business spend by business enum; employee-card seats; share of $5k+ transactions; entity type / revenue band / cash balance / PG willingness; personal holdings (premium Chase/Amex cards, Amex credit-card count, 5/24 count); ERP used (for surfacing integrations).

**Optimizer deltas**: cap-exhaustion overflow becomes the central mechanic at business volumes; approval filtering on the new axis; portfolio-level constraints (Amex ≤5, 5/24 exclusions); top-two selection for Business Gold; blended-rate reporting; optional float-days reporting.

**Registries to create**: `business-categories.yaml`, `business-usage-questions.yaml` (Dell purchases, business air travel, wireless, Indeed/Adobe-style credit gates), business point-valuations (UR/MR shared with consumer values; Brex points), issuer-rules registry.

**Deliberately out of scope**: traditional negotiated corporate programs (tier 4) as curated cards; early-pay-discount vs float tradeoff; APR optimization; merchant-level AP routing.

**Open questions for the build plan**: fork vs parameterize the engine (data roots are module constants — `scripts/optimize.py:37-39`); how the business journey mounts in the UI (separate route tree per "almost no shared assets" vs shared shell); whether float-days is scored or reported; archetype presets after the follow-up spend-profile research pass.

## Appendix — sources

Issuer/terms: Chase business cards compare page; Amex employee-cards help center; Amex Business Gold/Platinum product pages (spot-check via NerdWallet reviews); Brex account requirements; Brex pricing; Ramp pricing.
Editorial/guides: NerdWallet (best business cards; employee cards; Ramp vs Brex), The Points Guy (Ink guide; 5/24 guide; combining UR), Forbes Advisor, Upgraded Points (bank application rules; Ink over 5/24), One Mile at a Time (Amex 5-card limit; Amex points transfer), 10xTravel, Nav (EIN-only cards), Emburse (virtual cards).
CFO/treasury: J.P. Morgan Treasury Insights (commercial card value; business vs corporate), SVB (corporate card cash-management best practices), CFO.com (AP working-capital strategies), BILL/Divvy and Brex and Ramp blogs (employee cards, corporate vs business, no-PG cards).

Full URL list with extracted claims and quotes: `business-research-sources.jsonl` / `business-research-claims.jsonl` (session artifacts, kept out of the repo).
