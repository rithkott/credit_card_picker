# Card Curation Backlog

Master checklist of cards to hand-curate into `data/cards/`, following [curation-guide.md](curation-guide.md). Each entry shows the suggested file path slug. Check a card off only when its YAML reaches `confidence: high`.

Scope notes:
- **US consumer cards** in the main list, including **closed-loop store cards** (Target, Amazon Store Card, etc. — curated with the schema's `closed_loop` block) since they're worth recommending in combination with open-loop cards when a big share of someone's spend is at that merchant, and **credit-builder/secured cards** (curated with `approval.credit_tier: building`) so users with thin or damaged credit still get recommendations they can actually be approved for.
- Cards no longer open to new applicants (e.g. Amex EveryDay, US Bank Altitude Reserve) are excluded; the optimizer recommends cards people can actually get. If one is re-opened, add it.
- Product names, fees, and even issuers change (e.g. Bilt's issuer transition) — treat this list itself as needing verification during curation.

Suggested priority: **Tier 1** (the flat-rate + everyday-category cards most Americans actually hold) → **Tier 2** (premium travel + points ecosystems) → **Tier 3** (co-branded airline/hotel, store cards) → **Tier 4** (student/secured/credit-builder, niche).

---

## Chase — `data/cards/chase/`

- [ ] Freedom Flex — `freedom-flex` *(drafted, confidence: low — needs verification)*
- [ ] Freedom Unlimited — `freedom-unlimited`
- [ ] Freedom Rise — `freedom-rise`
- [ ] Sapphire Preferred — `sapphire-preferred` *(drafted, confidence: low — needs verification)*
- [ ] Sapphire Reserve — `sapphire-reserve`
- [ ] Slate Edge — `slate-edge`
- [ ] Prime Visa (Amazon) — `prime-visa`
- [ ] Instacart Mastercard — `instacart-mastercard`
- [ ] DoorDash Rewards Mastercard — `doordash-rewards`
- [ ] United Gateway — `united-gateway`
- [ ] United Explorer — `united-explorer`
- [ ] United Quest — `united-quest`
- [ ] United Club — `united-club`
- [ ] Southwest Rapid Rewards Plus — `southwest-plus`
- [ ] Southwest Rapid Rewards Premier — `southwest-premier`
- [ ] Southwest Rapid Rewards Priority — `southwest-priority`
- [ ] World of Hyatt — `world-of-hyatt`
- [ ] Marriott Bonvoy Boundless — `marriott-boundless`
- [ ] Marriott Bonvoy Bold — `marriott-bold`
- [ ] IHG One Rewards Premier — `ihg-premier`
- [ ] IHG One Rewards Traveler — `ihg-traveler`
- [ ] Aeroplan Card — `aeroplan`
- [ ] British Airways Visa Signature — `british-airways`
- [ ] Disney Premier Visa — `disney-premier`

## American Express — `data/cards/amex/`

- [ ] Blue Cash Everyday — `blue-cash-everyday`
- [ ] Blue Cash Preferred — `blue-cash-preferred` *(drafted, confidence: low — needs verification)*
- [ ] Gold — `gold` *(drafted, confidence: low — needs verification)*
- [ ] Green — `green`
- [ ] Platinum — `platinum`
- [ ] Delta SkyMiles Blue — `delta-blue`
- [ ] Delta SkyMiles Gold — `delta-gold`
- [ ] Delta SkyMiles Platinum — `delta-platinum`
- [ ] Delta SkyMiles Reserve — `delta-reserve`
- [ ] Hilton Honors — `hilton-honors`
- [ ] Hilton Honors Surpass — `hilton-surpass`
- [ ] Hilton Honors Aspire — `hilton-aspire`
- [ ] Marriott Bonvoy Bevy — `marriott-bevy`
- [ ] Marriott Bonvoy Brilliant — `marriott-brilliant`

## Citi — `data/cards/citi/`

- [ ] Double Cash — `double-cash` *(drafted, confidence: low — needs verification)*
- [ ] Custom Cash — `custom-cash`
- [ ] Strata Premier — `strata-premier`
- [ ] Strata Elite — `strata-elite`
- [ ] Rewards+ — `rewards-plus`
- [ ] Simplicity — `simplicity`
- [ ] Diamond Preferred — `diamond-preferred`
- [ ] Costco Anywhere Visa — `costco-anywhere`
- [ ] AAdvantage MileUp — `aadvantage-mileup`
- [ ] AAdvantage Platinum Select — `aadvantage-platinum-select`
- [ ] AAdvantage Executive — `aadvantage-executive`

## Capital One — `data/cards/capital-one/`

- [ ] Venture X — `venture-x` *(drafted, confidence: low — needs verification)*
- [ ] Venture — `venture`
- [ ] VentureOne — `venture-one`
- [ ] Savor — `savor`
- [ ] Quicksilver — `quicksilver`
- [ ] QuicksilverOne — `quicksilver-one`
- [ ] Platinum — `platinum`

## Discover — `data/cards/discover/`

- [ ] it Cash Back — `it-cash-back`
- [ ] it Chrome — `it-chrome`
- [ ] it Miles — `it-miles`
- [ ] it Student Cash Back — `it-student-cash-back`
- [ ] it Secured — `it-secured`

## Bank of America — `data/cards/bank-of-america/`

- [ ] Customized Cash Rewards — `customized-cash`
- [ ] Unlimited Cash Rewards — `unlimited-cash`
- [ ] Travel Rewards — `travel-rewards`
- [ ] Premium Rewards — `premium-rewards`
- [ ] Premium Rewards Elite — `premium-rewards-elite`
- [ ] Alaska Airlines Visa Signature — `alaska-airlines`
- [ ] BankAmericard — `bankamericard`

> Note: BofA's Preferred Rewards program boosts cash-back rates 25–75% by banking relationship tier — the schema may need a `relationship_multiplier` concept, or a note-level workaround, when these get curated.

## Wells Fargo — `data/cards/wells-fargo/`

- [ ] Active Cash — `active-cash` *(drafted, confidence: low — needs verification)*
- [ ] Autograph — `autograph`
- [ ] Autograph Journey — `autograph-journey`
- [ ] Attune — `attune`
- [ ] Reflect — `reflect`
- [ ] Bilt Mastercard — `bilt` *(verify current issuer/terms — Bilt has been transitioning off Wells Fargo)*

## U.S. Bank — `data/cards/us-bank/`

- [ ] Cash+ — `cash-plus`
- [ ] Altitude Go — `altitude-go`
- [ ] Altitude Connect — `altitude-connect`
- [ ] Shopper Cash Rewards — `shopper-cash-rewards`
- [ ] Smartly Visa — `smartly`

## Barclays — `data/cards/barclays/`

- [ ] JetBlue Card — `jetblue`
- [ ] JetBlue Plus — `jetblue-plus`
- [ ] AAdvantage Aviator Red — `aviator-red`
- [ ] Wyndham Rewards Earner — `wyndham-earner`
- [ ] Frontier Airlines World Mastercard — `frontier`

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

> Note: many of these have both a store-only version and an open-loop Visa/Mastercard version (e.g. Nordstrom, Verizon historically). Curate them as separate files — one with `closed_loop`, one without.

## Credit-builder & secured cards (use `approval.credit_tier: building`)

In scope so users with thin/damaged credit get real recommendations. Rewards are secondary here; approval accessibility is the point.

- [ ] Discover it Secured — `data/cards/discover/it-secured` *(also listed under Discover)*
- [ ] Capital One Platinum Secured — `data/cards/capital-one/platinum-secured`
- [ ] Capital One Quicksilver Secured — `data/cards/capital-one/quicksilver-secured`
- [ ] Chime Credit Builder Visa — `data/cards/chime/credit-builder`
- [ ] Self Visa Credit Card — `data/cards/self/visa`
- [ ] OpenSky Secured Visa — `data/cards/opensky/secured-visa`
- [ ] Mission Lane Visa — `data/cards/mission-lane/visa`
- [ ] Petal 2 Visa — `data/cards/petal/petal-2` *(verify still open to new applicants)*
- [ ] BankAmericard Secured — `data/cards/bank-of-america/bankamericard-secured`
- [ ] U.S. Bank Cash+ Secured — `data/cards/us-bank/cash-plus-secured`

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
- [ ] Luxury Card Mastercard Gold/Black/Titanium — `data/cards/luxury-card/…` *(niche premium; low priority)*

---

## Invite-only / by-invitation cards (separate — not recommendable by the optimizer)

These can't be applied for, so the optimizer should never recommend them; curate only if we later add a "value my existing cards" mode.

- Amex Centurion ("Black Card") — invitation only
- J.P. Morgan Reserve — invitation only (Chase Private Client / J.P. Morgan relationship)

## Business cards (separate — out of MVP scope)

Personal-spend optimization is the MVP; business cards involve different eligibility and spend patterns. Parking the common ones here for a future mode:

- Chase Ink Business Cash / Unlimited / Preferred / Premier
- Amex Blue Business Plus / Blue Business Cash / Business Gold / Business Platinum
- Capital One Spark Cash Plus / Spark Miles / Venture X Business
- U.S. Bank Business Triple Cash / Business Altitude Connect
- Bank of America Business Advantage Customized Cash / Unlimited Cash / Travel Rewards
- Citi AAdvantage Business / CitiBusiness cards
- Barclays AAdvantage Aviator Business
- Amex Delta SkyMiles Business (Gold/Platinum/Reserve), Hilton Business, Marriott Business
- Chase United Business / Southwest Business (Premier/Performance)

## Student cards (Tier 4)

- [ ] Discover it Student Cash Back — `data/cards/discover/it-student-cash-back` *(also listed under Discover)*
- [ ] Discover it Student Chrome — `data/cards/discover/it-student-chrome`
- [ ] Capital One Savor Student — `data/cards/capital-one/savor-student`
- [ ] Bank of America Customized Cash for Students — `data/cards/bank-of-america/customized-cash-students`
- Chase Freedom Rise (listed under Chase — aimed at new-to-credit)
