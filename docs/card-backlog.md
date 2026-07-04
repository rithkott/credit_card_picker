# Card Curation Backlog

Master checklist of cards to hand-curate into `data/cards/`, following [curation-guide.md](curation-guide.md). Each entry shows the suggested file path slug. Check a card off only when its YAML reaches `confidence: high`.

**This file is the tracking source of truth:** every file in `data/cards/` must appear here (the validator warns if one doesn't), and no card counts as done until a human has verified it against issuer terms — AI-drafted files are a starting point, not data.

**Status markers**:

- `[ ]` not added — no file in `data/cards/` yet
- `[~]` AI-drafted — file exists but `confidence: low`; numbers are plausible, not verified
- `[x]` human-verified — a person checked every number against issuer terms; `confidence: high`
- `[/]` Up-To-Date terms sheet present in data/offer_files for AI parsing

---

Scope notes:
- **US consumer cards** in the main list, including **closed-loop store cards** (Target, Amazon Store Card, etc. — curated with the schema's `closed_loop` block) since they're worth recommending in combination with open-loop cards when a big share of someone's spend is at that merchant, and **credit-builder/secured cards** (curated with `approval.credit_tier: building`) so users with thin or damaged credit still get recommendations they can actually be approved for.
- Cards no longer open to new applicants (e.g. Amex EveryDay, US Bank Altitude Reserve) are excluded; the optimizer recommends cards people can actually get. If one is re-opened, add it.
- Product names, fees, and even issuers change (e.g. Bilt's issuer transition) — treat this list itself as needing verification during curation.

Suggested priority: **Tier 1** (the flat-rate + everyday-category cards most Americans actually hold) → **Tier 2** (premium travel + points ecosystems) → **Tier 3** (co-branded airline/hotel, store cards) → **Tier 4** (student/secured/credit-builder, niche).

---

## Chase — `data/cards/chase/`

- [/] Freedom Flex — `freedom-flex`
- [/] Freedom Unlimited — `freedom-unlimited`
- [/] Freedom Rise — `freedom-rise`
- [/] Sapphire Preferred — `sapphire-preferred`
- [/] Sapphire Reserve — `sapphire-reserve`
- [/] Slate Edge — `slate-edge`
- [/] Prime Visa (Amazon) — `prime-visa`
- [/] Amazon Visa (Amazon) — `amazon-visa`
- [/] Instacart Mastercard — `instacart-mastercard`
- [/] DoorDash Rewards Mastercard — `doordash-rewards`
- [/] United Gateway — `united-gateway`
- [/] United Explorer — `united-explorer`
- [/] United Quest — `united-quest`
- [/] United Club — `united-club`
- [/] Southwest Rapid Rewards Plus — `southwest-plus`
- [/] Southwest Rapid Rewards Premier — `southwest-premier`
- [/] Southwest Rapid Rewards Priority — `southwest-priority`
- [/] World of Hyatt — `world-of-hyatt`
- [/] Marriott Bonvoy Boundless — `marriott-boundless`
- [/] Marriott Bonvoy Bold — `marriott-bold`
- [/] Marriott Bonvoy Bountiful - `mariott-bountiful`
- [/] IHG One Rewards Premier — `ihg-premier`
- [/] IHG One Rewards Traveler — `ihg-traveler`
- [/] Aeroplan Card — `aeroplan`
- [/] British Airways Visa Signature — `british-airways`
- [/] Aer Lingus Visa Signature — `aer-lingus`
- [/] Iberia Visa Signature — `iberia`
- [/] Disney Visa — `disney-visa`
- [/] Disney Premier Visa — `disney-premier`
- [/] Disney Inspire Visa — `disney-inspire`

## American Express — `data/cards/amex/`

- [/] Blue Cash Everyday — `blue-cash-everyday`
- [/] Blue Cash Preferred — `blue-cash-preferred`
- [/] Gold — `gold`
- [/] Green — `green`
- [/] Platinum — `platinum`
- [/] Delta SkyMiles Blue — `delta-blue`
- [/] Delta SkyMiles Gold — `delta-gold`
- [/] Delta SkyMiles Platinum — `delta-platinum`
- [/] Delta SkyMiles Reserve — `delta-reserve`
- [/] Hilton Honors — `hilton-honors`
- [/] Hilton Honors Surpass — `hilton-surpass`
- [/] Hilton Honors Aspire — `hilton-aspire`
- [/] Marriott Bonvoy Bevy — `marriott-bevy`
- [/] Marriott Bonvoy Brilliant — `marriott-brilliant`

## Citi — `data/cards/citi/`

- [/] Double Cash — `double-cash`
- [/] Strata — `strata`
- [/] Strata Premier — `strata-premier`
- [/] Strata Elite — `strata-elite`
- [/] Simplicity — `simplicity`
- [/] Diamond Preferred — `diamond-preferred`
- [/] Costco Anywhere Visa — `costco-anywhere`
- [/] AAdvantage MileUp — `aadvantage-mileup`
- [/] AAdvantage Platinum Select — `aadvantage-platinum-select`
- [/] AAdvantage Executive — `aadvantage-executive`
- [/] AAdvantage Globe — `aadvantage-globe`
- [/] AT&T Points Plus — `att-points-plus`

## Capital One — `data/cards/capital-one/`

- [/] Venture X — `venture-x`
- [/] Venture — `venture`
- [/] VentureOne — `venture-one`
- [/] Savor — `savor`
- [/] Quicksilver — `quicksilver`
- [/] QuicksilverOne — `quicksilver-one`
- [/] Platinum — `platinum`

## Discover — `data/cards/discover/`

- [/] it Cash Back — `it-cash-back`
- [/] it Chrome — `it-chrome`
- [/] it Miles — `it-miles`
- [/] it Student Cash Back — `it-student-cash-back`

## Bank of America — `data/cards/bank-of-america/`

- [/] Customized Cash Rewards — `customized-cash`
- [/] Unlimited Cash Rewards — `unlimited-cash`
- [/] Travel Rewards — `travel-rewards`
- [/] Premium Rewards — `premium-rewards`
- [/] Premium Rewards Elite — `premium-rewards-elite`
- [/] Atmos Rewards Ascent Visa Signature — `atmos-ascent` *(the former Alaska Airlines Visa — rebranded 2025 for the merged Alaska/Hawaiian "Atmos Rewards" program, $95 AF)*
- [/] Atmos Rewards Summit Visa Infinite — `atmos-summit` *(new premium tier, $395 AF, launched 2025)*
- [/] Allways Rewards Visa (formerly Allegiant World Mastercard) — `allegiant` *(renamed/network changed from Mastercard to Visa — verify)*
- [/] Air France KLM Flying Blue Visa Signature — `flying-blue` *(renamed/network changed from World Elite Mastercard — verify)*
- [/] Royal ONE Visa Signature — `royal-one` *(replaces the old Royal Caribbean Visa Signature card, March 2026; $0 AF)*
- [/] Royal ONE Plus Visa Signature — `royal-one-plus` *(new premium tier alongside Royal ONE, March 2026; $99 AF)*
- [/] BankAmericard — `bankamericard`

> Note: BofA's Preferred Rewards program boosts cash-back rates 25–75% by banking relationship tier — the schema may need a `relationship_multiplier` concept, or a note-level workaround, when these get curated.

## Wells Fargo — `data/cards/wells-fargo/`

- [/] Active Cash — `active-cash` *(drafted, confidence: low — needs verification; terms sheet refreshed)*
- [/] Autograph — `autograph`
- [/] Autograph Journey — `autograph-journey` *(Premier & Private Bank versions reportedly launched 2026 — verify whether separate products; research suggests they are relationship-tier variants of the same product, not distinct cards — see offer file)*
- [/] Reflect — `reflect`
- [/] Choice Privileges Mastercard — `choice-privileges`
- [/] Choice Privileges Select Mastercard — `choice-privileges-select`

> Bilt left Wells Fargo Feb 2026 — see the Cardless section below. Legacy WF Bilt cards were auto-converted to Autograph.

## Cardless (Bilt) — `data/cards/cardless/`

Bilt's three-card lineup ("Bilt Card 2.0") launched Feb 7, 2026, issued by Column N.A. and serviced by Cardless Inc. (replacing the single Wells Fargo Bilt card). Official product names confirmed via biltrewards.com newsroom + issuer terms:

- [/] Bilt Blue Card (no annual fee) — `bilt-blue`
- [/] Bilt Obsidian Card ($95 AF) — `bilt-obsidian`
- [/] Bilt Palladium Card ($495 AF) — `bilt-palladium`

## U.S. Bank — `data/cards/us-bank/`

- [/] Cash+ — `cash-plus`
- [/] Altitude Go — `altitude-go`
- [/] Altitude Connect — `altitude-connect`
- [/] Shopper Cash Rewards — `shopper-cash-rewards`
- [/] Smartly Visa — `smartly`

## Barclays — `data/cards/barclays/`

- [ ] JetBlue Card — `jetblue`
- [ ] JetBlue Plus — `jetblue-plus`
- [ ] AAdvantage Aviator Red — `aviator-red`
- [ ] Wyndham Rewards Earner — `wyndham-earner`
- [ ] Frontier Airlines World Mastercard — `frontier`
- [ ] Emirates Skywards Rewards World Elite — `emirates-skywards`
- [ ] Lufthansa Miles & More World Elite — `miles-and-more`
- [ ] Breeze Airways Mastercard — `breeze`
- [ ] My GM Rewards Mastercard — `my-gm-rewards`

## Synchrony — `data/cards/synchrony/`

- [ ] PayPal Cashback Mastercard — `paypal-cashback`
- [ ] Verizon Visa — `verizon-visa`
- [ ] Sam's Club Mastercard — `sams-club-mastercard`

## Store / closed-loop cards (use the schema's `closed_loop` block)

Usable only at their merchant, but often 5%-level rewards there — recommendable alongside open-loop cards when a big share of the user's spend is at that merchant. Verify current issuers; store-card portfolios get sold between banks often.

- [ ] Target Circle Card (TD Bank) — `data/cards/td-bank/target-circle`
- [ ] Amazon Store Card / Prime Store Card (Synchrony) — `data/cards/synchrony/amazon-store`
- [ ] My Best Buy Card (Citi) — `data/cards/citi/best-buy`
- [ ] Lowe's Advantage Card (Synchrony) — `data/cards/synchrony/lowes-advantage`
- [ ] Home Depot Consumer Card (Citi) — `data/cards/citi/home-depot`
- [ ] Kohl's Card (Capital One) — `data/cards/capital-one/kohls`
- [ ] Macy's Card (Citi) — `data/cards/citi/macys`
- [ ] Gap Good Rewards / Old Navy (Barclays) — `data/cards/barclays/gap-good-rewards`
- [ ] Nordstrom Card (TD Bank) — `data/cards/td-bank/nordstrom`
- [ ] OnePay Walmart Credit Card (OnePay/Synchrony, launched Dec 2025) — `data/cards/synchrony/onepay-walmart` *(verify: has both store-only and open-loop Mastercard versions)*
- [ ] REI Co-op Mastercard (Capital One) — `data/cards/capital-one/rei-co-op` *(open-loop, but REI-centric rewards)*

> Note: many of these have both a store-only version and an open-loop Visa/Mastercard version (e.g. Nordstrom, Verizon historically). Curate them as separate files — one with `closed_loop`, one without.

## Credit-builder & secured cards (use `approval.credit_tier: building`)

In scope so users with thin/damaged credit get real recommendations. Rewards are secondary here; approval accessibility is the point.

- [ ] Capital One Platinum Secured — `data/cards/capital-one/platinum-secured`
- [ ] Capital One Quicksilver Secured — `data/cards/capital-one/quicksilver-secured`
- [ ] Chime Credit Builder Visa — `data/cards/chime/credit-builder`
- [ ] Self Visa Credit Card — `data/cards/self/visa`
- [ ] OpenSky Secured Visa — `data/cards/opensky/secured-visa`
- [ ] Mission Lane Visa — `data/cards/mission-lane/visa`
- [ ] Petal 2 Visa — `data/cards/petal/petal-2` *(verify still open to new applicants)*
- [ ] BankAmericard Secured — `data/cards/bank-of-america/bankamericard-secured`
- [ ] U.S. Bank Cash+ Secured — `data/cards/us-bank/cash-plus-secured`

## PNC — `data/cards/pnc/`

- [ ] Cash Rewards Visa — `cash-rewards`
- [ ] Cash Unlimited Visa — `cash-unlimited`
- [ ] Spend Wise — `spend-wise` *(new 2026)*

## USAA — `data/cards/usaa/` *(military members/families)*

- [ ] Preferred Cash Rewards Visa — `preferred-cash-rewards`
- [ ] Rate Advantage Visa — `rate-advantage`

## Other issuers

- [ ] Apple Card (Goldman Sachs — verify current issuer) — `data/cards/goldman-sachs/apple-card`
- [ ] Fidelity Rewards Visa (Elan) — `data/cards/elan/fidelity-rewards`
- [ ] Robinhood Gold Card — `data/cards/robinhood/gold-card`
- [ ] Venmo Credit Card (Synchrony) — `data/cards/synchrony/venmo`
- [ ] SoFi Credit Card — `data/cards/sofi/credit-card`
- [ ] Navy Federal cashRewards — `data/cards/navy-federal/cash-rewards`
- [ ] Navy Federal Flagship Rewards — `data/cards/navy-federal/flagship-rewards`
- [ ] PenFed Platinum Rewards — `data/cards/penfed/platinum-rewards`
- [ ] PenFed Pathfinder Rewards — `data/cards/penfed/pathfinder`
- [ ] Alliant Cashback Visa Signature (2.5%) — `data/cards/alliant/cashback`
- [ ] TD Double Up — `data/cards/td-bank/double-up`
- [ ] Truist Enjoy Cash — `data/cards/truist/enjoy-cash`
- [ ] Upgrade Cash Rewards Visa — `data/cards/upgrade/cash-rewards`
- [ ] Bread Cashback American Express (2%) — `data/cards/bread-financial/bread-cashback`
- [ ] Max Cash Preferred (Elan, via many credit unions) — `data/cards/elan/max-cash-preferred`
- [ ] Luxury Card Mastercard Gold/Black/Titanium — `data/cards/luxury-card/…` *(niche premium; low priority)*



## Student cards (Tier 4)

- [/] Discover it Student Cash Back — `data/cards/discover/it-student-cash-back` *(also listed under Discover)*
- [ ] Discover it Student Chrome — `data/cards/discover/it-student-chrome`
- [ ] Capital One Savor Student — `data/cards/capital-one/savor-student`
- [ ] Bank of America Customized Cash for Students — `data/cards/bank-of-america/customized-cash-students`
- Chase Freedom Rise (listed under Chase — aimed at new-to-credit)
