# Competitive Research Findings

### The complaint that started this
NerdWallet, CreditCards.com, and The Points Guy don't "convincingly" pick a card for someone — they're largely affiliate-monetized content sites that publish generic "best cards of 2026" lists and light quiz-style tools, not a rigorous calculation against a user's real spend data.

### Competitive landscape

**1. Content/comparison sites (the ones the complaint is about)**
- NerdWallet, CreditCards.com, The Points Guy, WalletHub, Bankrate — editorial "best of" lists, some light quizzes (e.g. Bankrate's Spender Type Tool, NerdWallet CardMatch). Monetized by card-issuer affiliate commissions, which creates an inherent bias toward whichever cards pay out, not whichever card is mathematically best for the user. None of them ingest a user's actual transaction history or do real optimization math.

**2. Point-of-sale "which card should I swipe right now" apps**
- **MaxRewards** — syncs bank/card accounts, tells you the best card per purchase/category, ~800k users.
- **CardPointers** — manual card entry (no bank sync), checkout-time recommendations, tracks 5,000+ cards/900+ banks.
- **Kudos** — free browser extension + app, AI-driven, recommends best card at checkout across 2M+ retailers; mixed reviews, some complaints about miscategorized spend.
- **Wallaby** and **Birch Finance** — earlier entrants in this exact space; both are now defunct/shut down.
- Smaller/niche: AwardWallet (points tracking + merchant lookup), DisCard, Point Pilot, CardGenie, Mooch.
- Several open-source/hobby versions exist on GitHub (e.g. `ccreward-web`, `card-optimizer-skill`, `credit-card-optimizer`), mostly India/Singapore-focused or single-purchase-at-a-time tools built by individuals.

**3. Portfolio-construction / "which cards should I own" tools**
- This is closer to the idea being pursued here. It's notably thinner:
  - MaxRewards and Kudos both have a secondary feature suggesting *new* cards based on observed spending, but it's an upsell/affiliate feature layered on top of their point-of-sale product, not a rigorous combination optimizer (doesn't jointly account for annual fees, signup bonus value, category caps, or overlapping category coverage across multiple cards).
  - r/churning (Reddit) has a strong culture of manually-built spreadsheets for calculating optimal card combos, but these are DIY, not productized or self-serve.
  - No mainstream product does a true deterministic, multi-card optimization (like a knapsack/set-cover over annual fees vs. category multipliers vs. caps vs. signup bonuses) from a user's spend breakdown.

### Conclusion: is the idea taken?
Partially. The "which card do I swipe today" niche is crowded (MaxRewards, CardPointers, Kudos) and has already claimed two casualties (Wallaby, Birch Finance). But the specific angle here — a deterministic calculator that recommends the optimal *card or set of cards to hold*, computed from a person's real spending profile rather than editorial rankings or affiliate-weighted lists — is not well served by any mainstream product today. That's the differentiation opportunity.

### Decisions made from this research
- **Data philosophy:** The card/reward dataset must be a confirmed, hand-curated/validated set that we build and vet ourselves up front (not scraped or AI-generated on the fly), so recommendations can be calculated reliably and deterministically against it. This is a personal-use utility, not a monetization engine — no affiliate-driven bias in what gets recommended.
- **Product shape:** Build the portfolio-construction engine first — a deterministic optimizer that recommends the best card or combination of cards to hold, given a user's full spending profile (annual fees, signup bonuses, category caps, and overlap across cards all factored in). This targets the whitespace identified above rather than the crowded point-of-sale niche (MaxRewards/CardPointers/Kudos). A point-of-sale layer may be added later on top of the same reward-rate data, but is out of scope for now.
- **Spend input for MVP:** Manual category entry (user enters estimated spend per category — groceries, dining, travel, gas, etc.). No bank-linking/Plaid integration for the MVP — avoids the cost, compliance, and security surface area of handling real financial account data before the core idea is validated.
