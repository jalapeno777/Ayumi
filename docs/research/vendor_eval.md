# Copy Trading Platform Vendor Evaluation

**Research Manager | AYUAA-72**
**Date: 2026-04-02**
**Related: [AYUAA-61](/AYUAA/issues/AYUAA-61)**

---

## Executive Summary

Evaluated 7 copy trading platforms against Ayumi Group's requirements: cTrader/cAlgo compatibility, cost structure, minimum account size, profit share model, regulatory status, and API access.

**Top Recommendation:** **cTrader Copy** as the primary platform with **ZuluTrade** as a secondary/bride solution for MT4/MT5 compatibility.

---

## Platform Comparison Matrix

| Platform | cTrader/cAlgo Compatible | Cost Structure | Min Account | Profit Share | Regulatory Status | API Access |
|----------|-------------------------|----------------|-------------|--------------|-------------------|------------|
| **cTrader Copy** | ✅ Native | Performance + management + volume fees (provider-set) | Broker-dependent | 10-30% typical | Regulated (broker-level) | Full Open API |
| **ZuluTrade** | ⚠️ Via bridge | Free for investors; spread markup | $200-500 | Up to 50% | HCMC (Greece) regulated | REST API |
| **NAGA Autocopy** | ❌ Proprietary | Commission-based | $250 | Up to 50% | CySEC, FSA Seychelles | Limited API |
| **eToro** | ❌ Proprietary | Spread + overnight fees | $200 | ~1% daily performance | FCA, ASIC, CySEC | None (closed) |
| **Darwinex** | ❌ MT4 only | 15% performance fee + 10% management | £100 | 15-20% | FCA regulated | ZuluTrade API |
| **Myfxbook Autotrade** | ⚠️ MT4 only | Signal provider sets | $100 | Up to 30% | None ( signals marketplace) | Limited |
| **DupliTrade** | ❌ Proprietary | Performance fee | $500 | 20-50% | Regulated (broker-dependent) | Limited |

---

## Detailed Platform Analysis

### 1. cTrader Copy — **RECOMMENDED PRIMARY**

**Overview:** Native copy trading built into cTrader platform by Spotware.

**Strengths:**
- **Native cTrader/cAlgo integration** — no bridge required
- Full Open API access for custom development
- 800+ strategies, 200+ providers (as of 2026)
- Equity-to-equity ratio risk controls
- Multi-broker support via cTrader ecosystem
- Performance, management, and volume fee options

**Weaknesses:**
- Requires broker to support cTrader Copy
- cTrader less common than MT4 in some regions
- Smaller ecosystem than ZuluTrade

**Cost Structure:**
- Performance fee: Provider sets (typical 10-30%)
- Management fee: Provider sets (annual %)
- Volume fee: Per trade opened/closed
- No platform fee for investors

**Integration Path with cTrader Stack:**
- Seamless integration with existing cTrader
- Open API allows custom signal relay
- cBots can publish directly as strategies
- Lowest friction path to launch

**Regulatory Note:** Regulation depends on supporting broker. cTrader is used by FCA, CySEC, and other regulated brokers.

---

### 2. ZuluTrade — **RECOMMENDED SECONDARY**

**Overview:** Largest social trading platform with broker integration. Regulated in Greece by HCMC.

**Strengths:**
- **Multi-broker support** (MT4, MT5, cTrader, ActTrader, X Open Hub)
- Massive scale: 2M+ leaders, 30M+ accounts, 150+ countries
- ZuluGuard™ risk management
- Platform-agnostic (works with existing broker accounts)
- Free for investors (revenue from broker spread markup)

**Weaknesses:**
- Requires bridge/terminal connection for cTrader
- Complex fee structure (spread markup model)
- Less customizable than native API

**Cost Structure:**
- Free for investors (earns via spread markup)
- Leaders: Up to 50% performance fee
- Broker integration: spread markup participation

**Integration Path with cTrader Stack:**
- cTrader can connect via broker client ID
- May require broker-level partnership
- Alternative: use ZuluTrade as MT4/MT5 signal source

**Regulatory Status:** HCMC (Hellenic Capital Markets Commission) regulated in Greece. Passported across EEA.

---

### 3. NAGA Autocopy — **CONSIDER FOR COMMUNITY**

**Overview:** Social trading platform with NAGA ecosystem (trading, investing, payments).

**Strengths:**
- Strong community features (social feed, profiles)
- 2M+ registered users
- Best Social Trading Platform Europe 2025
- Multi-asset (stocks, forex, crypto, ETFs)

**Weaknesses:**
- **Not cTrader compatible** — proprietary platform
- Limited API access
- Complex regulatory structure (multiple entities)

**Cost Structure:**
- Commission-based trading
- Up to 50% performance fee for leaders
- Subscription tiers for premium features

**Regulatory Status:** CySEC regulated (Europe), FSA Seychelles (international).

---

### 4. eToro — **NOT RECOMMENDED**

**Overview:** Largest retail copy trading platform. Closed ecosystem.

**Strengths:**
- Massive brand recognition
- 30M+ users
- Popular for beginners

**Weaknesses:**
- **Closed ecosystem** — no API access
- **Not cTrader compatible**
- Complex fee structure
- Only their proprietary platform

**Cost Structure:**
- Spreads + overnight fees
- No external developer integration
- Performance fees built into platform

**Verdict:** Too closed for our use case. Good as a competitive reference.

---

### 5. Darwinex — **ARCHITECTURAL INTEREST ONLY**

**Overview:** UK-based platform focusing on trader evaluation and funding.

**Strengths:**
- **FCA regulated**
- Trader "Darwin" evaluation metrics
- Popular in Europe

**Weaknesses:**
- **MT4 only** — no cTrader support
- Uses ZuluTrade infrastructure
- Limited customization

**Cost Structure:**
- 15% performance fee
- 10% management fee
- £100 minimum

**Verdict:** Interesting regulated model but MT4-only limits integration with our cTrader stack.

---

### 6. Myfxbook Autocopy — **LOW PRIORITY**

**Overview:** Signal marketplace for MT4 traders.

**Strengths:**
- Low minimum ($100)
- Many signal providers

**Weaknesses:**
- **MT4 only**
- No formal regulation
- Limited API

**Cost Structure:**
- Provider sets fee (up to 30%)
- Platform takes cut

**Verdict:** Too limited for cTrader-based strategy.

---

### 7. DupliTrade — **NOT RECOMMENDED**

**Overview:** Proprietary copy trading platform.

**Strengths:**
- Established in Middle East/Asia

**Weaknesses:**
- **Proprietary platform**
- Limited broker compatibility
- No API access
- Complex integration

**Cost Structure:**
- Performance fees 20-50%
- $500 minimum

**Verdict:** Closed platform, not suitable for our needs.

---

## Scoring Summary

| Platform | cTrader Compatible | Cost | Min Account | Profit Share | Regulation | API Access | **TOTAL** |
|----------|:-----------------:|:----:|:----------:|:-----------:|:----------:|:----------:|:---------:|
| cTrader Copy | 10 | 7 | 8 | 8 | 8 | 10 | **51** |
| ZuluTrade | 6 | 8 | 7 | 9 | 9 | 7 | **46** |
| NAGA | 2 | 6 | 7 | 9 | 7 | 3 | **34** |
| eToro | 1 | 5 | 7 | 5 | 9 | 1 | **28** |
| Darwinex | 3 | 7 | 7 | 7 | 10 | 4 | **38** |
| Myfxbook | 3 | 7 | 9 | 6 | 2 | 3 | **30** |
| DupliTrade | 2 | 5 | 5 | 7 | 6 | 2 | **27** |

*Scoring: 1-10 scale, 10 = best*

---

## Integration Path with cTrader Stack

### Phase 1: cTrader Native (Launch)
1. Partner with cTrader broker(s) that support cTrader Copy
2. Configure strategy provider accounts
3. Leverage cTrader Open API for custom integration layer
4. Connect existing cBots as strategies

### Phase 2: Multi-Platform (Scale)
1. Explore ZuluTrade broker integration for MT4/MT5 signals
2. Use ZuluTrade as bridge to reach non-cTrader traders
3. Build custom signal relay using cTrader Open API → ZuluTrade

### Phase 3: Community (Differentiate)
1. Build Ayumi community layer on top
2. ICT/SMC methodology focus as differentiator
3. Custom risk management and reporting

---

## Recommendation

### Primary: cTrader Copy
- **Why:** Native cTrader integration, full API access, lowest friction
- **Action:** Identify supporting brokers, configure provider accounts, test Open API

### Secondary: ZuluTrade  
- **Why:** Scale, multi-broker support, proven track record
- **Action:** Explore broker partnership for MT4/MT5 signal reach

### Do Not Pursue: eToro, DupliTrade
- **Why:** Closed ecosystems, no API access, incompatible with cTrader stack

---

## Risks and Considerations

### Regulatory
- Copy trading regulation varies by jurisdiction
- Retail copy trading restricted in some EU countries (ESMA)
- Professional trader designation may allow broader access

### Technical
- cTrader Open API requires broker cooperation
- Signal latency between platforms
- Risk management across copied accounts

### Commercial
- Revenue share with platform providers
- Broker relationship dependencies
- Competition with established players

---

## Data Limitations

*Real-time pricing and fee structures should be verified directly with platforms before final decision. Figures above are based on publicly available information and may have changed.*

---

## Next Steps

1. **Kai (Forex/Eng):** Review cTrader Open API documentation for copy-trading capabilities
2. **Research Team:** Reach out to cTrader broker partners for integration requirements
3. **Business Dev:** Contact ZuluTrade for broker partnership details
4. **Legal/Compliance:** Assess regulatory requirements for target markets