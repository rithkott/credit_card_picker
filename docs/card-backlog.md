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
- **Mainstream US consumer cards only.** The July 2026 scope cut removed the small, niche cards that only maximized point value for edge-case spenders: closed-loop store cards (Target, Amazon Store Card, Nordstrom, OnePay/Walmart, …), credit-builder/secured cards, standalone student cards, U.S. Bank's lineup, Luxury Card, small credit-union one-offs (Max Cash Preferred), theme-park-currency co-brands (Disney), and no-rewards balance-transfer cards (Slate Edge). Users steer recommendations with `reward_preferences` (flights / hotels / cashback / total_value) instead of the dataset carrying every niche product. The schema's `closed_loop` block and `approval.credit_tier: building` remain supported if scope ever widens again — but don't add such cards without revisiting this decision.
- Cards no longer open to new applicants (e.g. Amex EveryDay, US Bank Altitude Reserve) are excluded; the optimizer recommends cards people can actually get. If one is re-opened, add it.
- Product names, fees, and even issuers change (e.g. Bilt's issuer transition) — treat this list itself as needing verification during curation.

Suggested priority: **Tier 1** (the flat-rate + everyday-category cards most Americans actually hold) → **Tier 2** (premium travel + points ecosystems) → **Tier 3** (co-branded airline/hotel/other, remaining niche).

---

## Chase — `data/cards/chase/`

- [~] Freedom Flex — `freedom-flex`
- [~] Freedom Unlimited — `freedom-unlimited`
- [~] Freedom Rise — `freedom-rise`
- [~] Sapphire Preferred — `sapphire-preferred`
- [~] Sapphire Reserve — `sapphire-reserve`
- [~] Prime Visa (Amazon) — `prime-visa`
- [~] Amazon Visa (Amazon) — `amazon-visa`
- [~] Instacart Mastercard — `instacart-mastercard`
- [~] DoorDash Rewards Mastercard — `doordash-rewards`
- [~] United Gateway — `united-gateway`
- [~] United Explorer — `united-explorer`
- [~] United Quest — `united-quest`
- [~] United Club — `united-club`
- [~] Southwest Rapid Rewards Plus — `southwest-plus`
- [~] Southwest Rapid Rewards Premier — `southwest-premier`
- [~] Southwest Rapid Rewards Priority — `southwest-priority`
- [~] World of Hyatt — `world-of-hyatt`
- [~] Marriott Bonvoy Boundless — `marriott-boundless`
- [~] Marriott Bonvoy Bold — `marriott-bold`
- [~] Marriott Bonvoy Bountiful - `marriott-bountiful`
- [~] IHG One Rewards Premier — `ihg-premier`
- [~] IHG One Rewards Traveler — `ihg-traveler`
- [~] Aeroplan Card — `aeroplan`
- [~] British Airways Visa Signature — `british-airways`
- [~] Aer Lingus Visa Signature — `aer-lingus`
- [~] Iberia Visa Signature — `iberia`

## American Express — `data/cards/amex/`

- [~] Blue Cash Everyday — `blue-cash-everyday`
- [~] Blue Cash Preferred — `blue-cash-preferred`
- [~] Gold — `gold`
- [~] Green — `green`
- [~] Platinum — `platinum`
- [~] Delta SkyMiles Blue — `delta-blue`
- [~] Delta SkyMiles Gold — `delta-gold`
- [~] Delta SkyMiles Platinum — `delta-platinum`
- [~] Delta SkyMiles Reserve — `delta-reserve`
- [~] Hilton Honors — `hilton-honors`
- [~] Hilton Honors Surpass — `hilton-surpass`
- [~] Hilton Honors Aspire — `hilton-aspire`
- [~] Marriott Bonvoy Bevy — `marriott-bevy`
- [~] Marriott Bonvoy Brilliant — `marriott-brilliant`

## Citi — `data/cards/citi/`

- [~] Double Cash — `double-cash`
- [~] Strata — `strata`
- [~] Strata Premier — `strata-premier`
- [~] Strata Elite — `strata-elite`
- [~] Simplicity — `simplicity`
- [~] Diamond Preferred — `diamond-preferred`
- [~] Costco Anywhere Visa — `costco-anywhere`
- [~] AAdvantage MileUp — `aadvantage-mileup`
- [~] AAdvantage Platinum Select — `aadvantage-platinum-select`
- [~] AAdvantage Executive — `aadvantage-executive`
- [~] AAdvantage Globe — `aadvantage-globe`
- [~] AT&T Points Plus — `att-points-plus`

## Capital One — `data/cards/capital-one/`

- [~] Venture X — `venture-x`
- [~] Venture — `venture`
- [~] VentureOne — `venture-one`
- [~] Savor — `savor`
- [~] Quicksilver — `quicksilver`
- [~] QuicksilverOne — `quicksilver-one`
- [~] Platinum — `capital-one-platinum`

## Discover — `data/cards/discover/`

- [~] it Cash Back — `it-cash-back`
- [~] it Chrome — `it-chrome`
- [~] it Miles — `it-miles`
- [~] it Student Cash Back — `it-student-cash-back`

## Bank of America — `data/cards/bank-of-america/`

- [~] Customized Cash Rewards — `customized-cash`
- [~] Unlimited Cash Rewards — `unlimited-cash`
- [~] Travel Rewards — `travel-rewards`
- [~] Premium Rewards — `premium-rewards`
- [~] Premium Rewards Elite — `premium-rewards-elite`
- [~] Atmos Rewards Ascent Visa Signature — `atmos-ascent` *(the former Alaska Airlines Visa — rebranded 2025 for the merged Alaska/Hawaiian "Atmos Rewards" program, $95 AF)*
- [~] Atmos Rewards Summit Visa Infinite — `atmos-summit` *(new premium tier, $395 AF, launched 2025)*
- [~] Allways Rewards Visa (formerly Allegiant World Mastercard) — `allegiant` *(renamed/network changed from Mastercard to Visa — verify)*
- [~] Air France KLM Flying Blue Visa Signature — `flying-blue` *(renamed/network changed from World Elite Mastercard — verify)*
- [~] Royal ONE Visa Signature — `royal-one` *(replaces the old Royal Caribbean Visa Signature card, March 2026; $0 AF)*
- [~] Royal ONE Plus Visa Signature — `royal-one-plus` *(new premium tier alongside Royal ONE, March 2026; $99 AF)*
- [~] BankAmericard — `bankamericard`

> Note: BofA's Preferred Rewards program boosts cash-back rates 25–75% by banking relationship tier — the schema may need a `relationship_multiplier` concept, or a note-level workaround, when these get curated.

## Wells Fargo — `data/cards/wells-fargo/`

- [~] Active Cash — `active-cash` *(drafted, confidence: low — needs verification; terms sheet refreshed)*
- [~] Autograph — `autograph`
- [~] Autograph Journey — `autograph-journey` *(Premier & Private Bank versions reportedly launched 2026 — verify whether separate products; research suggests they are relationship-tier variants of the same product, not distinct cards — see offer file)*
- [~] Reflect — `reflect`
- [~] Choice Privileges Mastercard — `choice-privileges`
- [~] Choice Privileges Select Mastercard — `choice-privileges-select`

> Bilt left Wells Fargo Feb 2026 — see the Cardless section below. Legacy WF Bilt cards were auto-converted to Autograph.

## Cardless (Bilt) — `data/cards/cardless/`

Bilt's three-card lineup ("Bilt Card 2.0") launched Feb 7, 2026, issued by Column N.A. and serviced by Cardless Inc. (replacing the single Wells Fargo Bilt card). Official product names confirmed via biltrewards.com newsroom + issuer terms:

- [~] Bilt Blue Card (no annual fee) — `bilt-blue`
- [~] Bilt Obsidian Card ($95 AF) — `bilt-obsidian`
- [~] Bilt Palladium Card ($495 AF) — `bilt-palladium`

## Barclays — `data/cards/barclays/`

- [~] JetBlue Card — `jetblue`
- [~] JetBlue Plus — `jetblue-plus`
- [~] JetBlue Premier — `jetblue-premier`
- [~] RCI Elite Rewards - `rci-elite`
- [ ] Capital Vacations - `capital-vacations`
- [ ] AAdvantage Aviator Red — `aviator-red`
- [~] Wyndham Rewards Earner — `wyndham-earner`
- [~] Wyndham Rewards Earner Plus — `wyndham-plus`
- [~] Frontier Airlines World Mastercard — `frontier`
- [~] Emirates Skywards Rewards World Elite — `emirates-skywards`
- [~] Emirates Skywards Rewards Premier World Elite — `emirates-premier`
- [~] Lufthansa Miles & More World Elite — `miles-and-more`
- [ ] Breeze Airways Mastercard — `breeze` *(actual live product is "Breeze Easy Visa Signature" — Visa network, not Mastercard; see offer file)*
- [~] My GM Rewards Mastercard — `my-gm-rewards`

## Synchrony — `data/cards/synchrony/`

- [~] PayPal Cashback Mastercard — `paypal-cashback`
- [~] Verizon Visa — `verizon-visa`
- [~] Sam's Club Mastercard — `sams-club-mastercard`

## Other issuers

- [~] Apple Card (Goldman Sachs — verify current issuer) — `data/cards/goldman-sachs/apple-card`
- [~] Fidelity Rewards Visa (Elan) — `data/cards/elan/fidelity-rewards`
- [~] Robinhood Gold Card — `data/cards/robinhood/gold-card`
- [~] Venmo Credit Card (Synchrony) — `data/cards/synchrony/venmo`
- [~] SoFi Credit Card — `data/cards/sofi/credit-card`
- [~] Navy Federal cashRewards — `data/cards/navy-federal/cash-rewards`
- [~] Navy Federal cashRewards Plus — `data/cards/navy-federal/cash-rewards-plus`
- [~] Navy Federal Flagship Rewards — `data/cards/navy-federal/flagship-rewards`
- [~] PenFed Platinum Rewards — `data/cards/penfed/platinum-rewards`
- [~] PenFed Pathfinder Rewards — `data/cards/penfed/pathfinder`
- [~] Alliant Cashback Visa Signature (2.5%) — `data/cards/alliant/cashback`
- [~] TD Double Up — `data/cards/td-bank/double-up`
- [~] Truist Enjoy Cash (3-2-1 tiered) — `data/cards/truist/enjoy-cash-3-2-1`
- [~] Truist Enjoy Cash (1.5% flat) — `data/cards/truist/enjoy-cash-1-5-flat`
- [~] Upgrade Cash Rewards Visa — `data/cards/upgrade/upgrade-cash-rewards`
- [~] Bread Cashback American Express (2%) — `data/cards/bread-financial/bread-cashback`
