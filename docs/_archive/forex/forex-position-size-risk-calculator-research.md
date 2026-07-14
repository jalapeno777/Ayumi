# Forex Position Size / Risk Calculator — Freemium SaaS Research

**Issue:** AVA-1767 | **Status:** in_progress

---

## What Traders Actually Search For (Feature Demand)

Position size calculators are commodity tools — BabyPips, Myfxbook, EarnForex, Dukascopy all offer free versions. Core features forex traders search for:

1. **Account currency + size** — deposit, balance
2. **Risk % or fixed $ amount** — standard 1-2% per trade
3. **Stop-loss pips** — the main input
4. **Currency pair** — auto-calculates cross-pair pip values
5. **Lot size / units output**
6. **Pip value** — often bundled as a related tool

**Differentiators that drive preference:**
- Clean, fast UI (mobile/desktop)
- Multi-account support
- Preset setups for prop firm rules
- Risk/reward ratio calculator
- Margin calculator

**What's notably absent from free tools:** multi-account portfolio view, prop firm drawdown tracking, trade journal integration.

---

## Build Complexity Assessment

| Layer | Complexity | Notes |
|-------|-----------|-------|
| Core calc logic | Low | Pure math — pip value, position size, risk % |
| Cross-pair pip values | Low-Medium | Requires exchange rate lookup |
| Mobile UI | Medium | React/Next.js static page, ~2-4 weeks |
| Freemium model | Medium | Auth, tier limits, payment integration |
| Real-time FX rates | Low-Medium | Free API (exchangerate-api, frankfurter.app) |
| Prop firm presets | Low | Lookup table for FTMO/FTMO rules |

**Estimated full build (standalone web app):** 6-10 weeks solo dev
**Estimated TradingView indicator build:** 1-2 weeks Pine Script

---

## Distribution Channel Analysis

### Option A: TradingView Indicator (Pine Script)

**Revenue model:** TradingView takes 50% of indicator/strategy sales.

**Pros:**
- Built-in audience of millions of traders
- No separate hosting/payment infrastructure needed
- Easy embed in existing workflow

**Cons:**
- Revenue share model — 50% to TV
- Pine Script is limited — no persistent state, no external API calls
- Restricted to TradingView platform
- Cannot capture emails/build audience for upsell
- Position size calc has low perceived value as standalone indicator

**Realistic revenue estimate:** Position size calc indicators rarely sold at premium. Most successful TV indicators are signal/strategy tools, not calculators. Estimate $50-200/month if monetizable at all.

### Option B: Standalone Web App via Gumroad/Lemon Squeezy

**Revenue model:** Direct sale, one-time payment or freemium subscription.

**Platform comparison:**

| Platform | Fee | Tax/MoR | Subscriptions | Best For |
|---------|-----|---------|---------------|---------|
| Lemon Squeezy | 5% + 50¢ | Yes (global) | Yes | SaaS products, global audience |
| Gumroad | 10% + ~3% | No | No | Simple digital goods, US-focused |

**Lemon Squeezy advantage:** Handles global VAT/tax automatically, supports subscriptions, has affiliate network, ~3x better conversion per testimonials. **Recommendation: Lemon Squeezy over Gumroad.**

**Estimated Lemon Squeezy revenue (freemium model):**
- Free tier: ~500-2000 users/month (based on Google Play calculator download volumes)
- Paid tier ($5-10/month): 2-5% conversion = 10-100 paying users = **$50-1000/month**
- One-time payment option ($25-50): additional revenue stream

**Realistic estimate for a well-executed position size calculator with prop firm features:** $200-800/month within 6 months, assuming SEO and community presence (Discord/YouTube).

---

## Build vs. Buy Recommendation

**Recommendation: BUILD standalone web app via Lemon Squeezy**

**Rationale:**

1. **Position size calculator is a commodity** — but prop firm-specific features are not. Embedding FTMO/FTMO drawdown rules, multi-account tracking, and trading journal integration elevates it above free tools.
2. **Higher revenue potential** — Direct sale model keeps 95% (vs. 50% via TradingView). Freemium with $5-10/month tier realistic.
3. **Audience capture** — Lemon Squeezy email list + upsell to signal service or education content.
4. **TradingView indicator** — Too limited for a full experience; position size calc doesn't fit TV's signal/strategy use case.
5. **Build complexity** — Moderate. Static web app + Pine Script version for TradingView as free lead-gen is viable.

**Hybrid approach:**
- Build standalone web app (React/Next.js) as primary product
- Build free Pine Script indicator for TradingView as lead-generation tool (drive users to web app)
- Monetize via Lemon Squeezy freemium tier

**Estimated build timeline:** 8-12 weeks to paid tier launch
**Revenue potential (year 1):** $300-1500/month steady state

---

## Next Steps

1. **Board decision:** Approve standalone web app approach with Lemon Squeezy?
2. **UX/mVP scope:** Define free vs. paid tier feature split
3. **Tech stack decision:** Next.js vs. vanilla HTML + Lemon Squeezy embed
4. **Content strategy:** How does this tie into forex education content pipeline?