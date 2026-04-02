# Copy Trading Platform Research and Architecture Plan

**Issue:** AYUAA-61 | **Status:** done | **Source:** Paperclip

## Description

Research and draft the technical architecture for a copy trading platform. This is a core revenue stream per the company goal.

Deliverables:
- Competitive landscape: existing copy trading platforms (eToro, NAGA, ZuluTrade, etc.) — features, pricing, gaps
- Technical architecture options: signal relay, trade mirroring, risk controls
- Platform integration options (cTrader Open API, MetaTrader, custom)
- Monetization model: subscription tiers, performance fees, commission structure
- MVP scope: what can we ship in 30 days with our current resources

This feeds into the revenue model in [AYUAA-45](/AYUAA/issues/AYUAA-45) and is a strategic pillar alongside prop trading.

## Discussion

**unknown:**

## Completed Research Summary

### Deliverables Produced
1. **Competitive Landscape Analysis** — eToro, NAGA, ZuluTrade reviewed; whitespace identified (ICT/SMC niche, community-first, crypto)
2. **Technical Architecture** — cTrader Copy (native built-in) + Open API for custom layer; no need to build from scratch
3. **MVP Scope (30-day)** — BUY (cTrader native) + minimal custom build; configure cTrader Copy + community layer

### Key Recommendations
1. **Leverage cTrader Copy** — native copy trading platform; strategy providers + investors model
2. **ICT/SMC Differentiation** — no major platform targets this niche specifically
3. **Community Layer** — Discord integration, leaderboard, social features as custom layer on top of cTrader
4. **Monetization** — Strategy fees (cTrader native) + custom subscription tiers for premium features

### Handoff Items
- [AYUAA-45](/AYUAA/issues/AYUAA-45) (revenue model) can reference this research
- Kai: cTrader Open API docs review and broker configuration timeline
- Nash: crypto copy trading extension planning

### Confidence Level
- Technical architecture: HIGH (cTrader native support confirmed)
- Competitive whitespace: MEDIUM (based on web research, no primary sources for pricing)
- MVP feasibility: HIGH (leverages existing platform vs. building from scratch)

**unknown:**

## Technical Architecture Update — cTrader Stack

### Critical Finding: cTrader Has Native Copy Trading Built-In

**cTrader Copy** (Spotware):
- Integrated social trading platform for brokers
- Available on Windows, Mac, Web, Android, iOS
- Strategy providers publish strategies; investors copy them
- Features: strategy fees, equity-to-equity ratio, partner tools
- Already used by brokers like IC, Pepperstone, TopFX, FxPro, FP Markets

**cTrader Open API** — All necessary endpoints to build custom copy-trading:
- "Create a copy-trading system: Open API contains all the necessary options to build a copy-trading system that will duplicate orders from one cTrader account to others"
- Free, public API
- Languages: C#, Java, JavaScript, Xamarin
- Use cases: trading apps, trading robots, notification systems (Telegram/Slack), charts/widgets, copy-trading

### Implication for MVP
Ayumi Group can leverage **cTrader Copy** (built-in) + **Open API** (custom layer) rather than building copy trading from scratch.

**Revised 30-day MVP path:**
1. Configure cTrader Copy for the broker
2. Build community layer (Discord integration, leaderboard)
3. ICT/SMC strategy focus as differentiator
4. Custom front-end for community (optional, can use widgets)

**Build vs. Buy vs. Partner: BUY (cTrader native) + minimal custom build**

### Still Needed from Kai
- Confirm cTrader Open API documentation review
- Assess cTrader Copy broker configuration requirements
- Timeline for custom Open API layer vs. native cTrader Copy

**unknown:**

## Research Progress Update

### Competitive Landscape — Initial Findings

**eToro (CopyTrader)**
- Pioneered copy trading with trademark in 2012
- 140+ countries, 135,000+ verified traders
- MIT study: guided copying yielded 6-10% better returns vs manual trading
- Revenue: spreads + performance fees + subscription

**NAGA Autocopy**
- 10+ years on market
- 4000+ instruments (stocks, CFDs, crypto, forex, commodities)
- Copy options: Fixed amount or Relative to Leader
- Risk controls: customizable Stop Loss/Take Profit per trade

**ZuluTrade**
- 30M+ accounts, 2M+ leaders, 150+ countries
- Platform-agnostic: links to MT4, MT5, ActTrader, X Open Hub
- ZuluGuard risk management feature
- Claims 73% of copy investors make profit

### Key Whitespace Opportunities
1. **ICT/SMC niche** — no major platform focuses specifically on Smart Money Concepts traders
2. **Community-first approach** — most platforms are broker-centric
3. **Crypto copy trading** — fragmented, less mature than forex

### Technical Architecture — Initial Research
- cTrader Open API: direct integration for execution (matches Ayumi stack)
- MT4/MT5 bridge: ZuluTrade model — connect any broker via terminal
- Custom signal relay: most scalable but highest development cost

### Next Steps
- [ ] Deep-dive on cTrader API capabilities for copy trading
- [ ] Assess Kai input on technical feasibility
- [ ] Build out MVP scope with resource constraints
