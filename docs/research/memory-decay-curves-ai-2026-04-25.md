# Research: Memory Decay Curves for AI Systems

**Queue ID:** MEM-RES-9d45574b
**Date:** 2026-04-25
**Issue:** [AYUAA-852](/AYUAA/issues/AYUAA-852)
**Status:** complete

## Context

Phase 1 decay curve implementation for Ava memory infrastructure. Investigates how memory decay works in AI systems, adapting Ebbinghaus forgetting curve, spaced repetition, and similar models.

---

## 1. Ebbinghaus Forgetting Curve

### Original Model (1885)

Hermann Ebbinghaus's classic forgetting curve describes exponential decay of memory retention over time without reinforcement:

```
R = e^(-t/S)
```

Where:
- R = retention (0-1)
- t = time elapsed
- S = stability coefficient (memory strength)

**Key empirical findings:**
- ~40% retention after 20 minutes
- ~25% retention after 1 hour
- ~20% retention after 1 day
- ~10% retention after 6 days
- Stabilizes around ~5% with no review

### Modern Refinements

Recent research (2025) shows the classic Ebbinghaus model underperforms compared to sigmoid and inverse decay functions for AI memory systems. Key refinements:

1. **Sigmoid Decay** — Better models initial stability followed by gradual decay, then plateau
2. **Inverse Decay** — Models rapid initial forgetting that slows over time
3. **Power Law Decay** — Better fit for longer retention intervals

**Reference:** "Is there a better way to forget? Modelling Memory Decay in Deep..." (ScienceDirect, Nov 2025)

### AI Agent Implementation

Dev.to implementation (March 2026) applies Ebbinghaus forgetting curve to AI memory:
- Memories decay based on importance score and time elapsed
- Each retrieval resets the decay clock
- Decay rate modulated by emotional salience (from importance scoring research)

---

## 2. Spaced Repetition Algorithms

### SM-2 Algorithm

Used by Anki, SuperMemo, and most spaced repetition systems.

**Core Variables:**
- `n` — repetition number
- `EF` — easiness factor (initially 2.5)
- `interval` — days until next review

**Formula:**
```
EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
EF' = max(1.3, EF')

if q < 3:
    interval = 1
else:
    if n == 1: interval = 1
    elif n == 2: interval = 6
    else: interval = interval * EF
```

Where q = quality of response (0-5)

**Limitations of SM-2:**
- Initial intervals are rigid (1 day, 6 days)
- EF adjustment is formulaic
- Does not account for item difficulty independently from user performance

### FSRS (Free Spaced Repetition Scheduler)

Modern algorithm (2022+) used in Anki as alternative to SM-2. Based on the "Three Component Model of Memory."

**Three Components:**
1. **Stability** — How long until memory decays to threshold
2. **Retrievability** — Current probability of successful recall
3. **Difficulty** — Resistance to learning

**Advantages over SM-2:**
- Personalizes to individual memory patterns
- Accounts for item-level difficulty
- More efficient review scheduling (20-40% fewer reviews for same retention)
- Better handles "overdue" items

**Reference:** [FSRS4Anki Wiki](https://github.com/open-spaced-repetition/fsrs4anki/wiki/abc-of-fsrs)

### SuperMemo's SM-18

Most complex algorithm in SuperMemo family. Uses 21 parameters for fine-grained modeling. Computationally expensive but highest precision.

---

## 3. Time-Based vs Access-Based Decay

### Time-Based Decay

Memory decays based purely on elapsed time since last review/access.

**Pros:**
- Simple to implement
- Predictable behavior
- No tracking overhead

**Cons:**
- Ignores actual memory usage patterns
- May discard frequently-accessed but temporally-old memories
- Poor for bursty access patterns

### Access-Based Decay

Memory decay is triggered by access count or retrieval events.

**Pros:**
- Better models actual usage value
- More adaptive to bursty access
- Allows "refreshing" through access

**Cons:**
- Requires tracking access counts
- Doesn't account for time-based natural forgetting
- Vulnerable to thrashing (constant access prevents decay)

### Hybrid Approach (Recommended)

Combines time-based decay with access-based reinforcement:

```
decay_score = base_decay(time_elapsed) * access_modifier(access_count)
```

Where:
- `base_decay` follows Ebbinghaus curve (exponential or sigmoid)
- `access_modifier` = 1 / (1 + decay_rate * access_count)

This matches neuroscience: both recency AND usage frequency determine memory importance.

---

## 4. Critical Memory Preservation

### Protection Mechanisms

Not all memories should decay equally. Critical memories require preservation:

**Levels of Protection:**

| Level | Criteria | Decay Behavior |
|-------|----------|----------------|
| **Protected** | Governance-critical, ownership, certifications | No automatic decay; explicit archival required |
| **Standard** | Normal episodic events | Ebbinghaus-based decay |
| **Transient** | Cache-like temporary states | Fast decay, may be evicted proactively |

**Protection Signals (from importance scoring research):**
- Importance score ≥ 4 → protected or slow decay
- Importance score 2-3 → standard decay
- Importance score 1 → fast decay / proactive forgetting

**Implementation:**
```python
def compute_decay(importance: float, time_elapsed: float, access_count: int) -> float:
    base_decay = math.exp(-time_elapsed / STABILITY_COEFFICIENT)
    access_boost = 1 / (1 + DECAY_RATE * access_count)
    
    if importance >= 4:
        return base_decay * access_boost * PROTECTED_SLOWDOWN  # ~0.1x decay rate
    elif importance >= 2:
        return base_decay * access_boost
    else:
        return base_decay * access_boost * PROACTIVE_FORGET_MULTIPLIER  # ~2-3x decay rate
```

---

## 5. Parameter Tuning

### Key Parameters

| Parameter | Description | Typical Range | Tuning Method |
|-----------|-------------|---------------|---------------|
| Stability (S) | Base memory half-life | 1-30 days | Retention testing |
| Easiness Factor (EF) | Per-item difficulty modifier | 1.3-3.0 | User feedback |
| Decay Rate | Access-based decay multiplier | 0.01-0.1 | A/B testing |
| Protected Threshold | Min importance for protection | 3-4 | Domain-specific |
| Review Interval | Spaced repetition intervals | 1-180 days | Algorithm-based |

### Tuning Methodology

**Phase 1 (Initial):**
1. Start with Ebbinghaus baseline: S = 7 days (half-life)
2. Set importance thresholds per scoring research
3. Use access_count = 1 for first review, exponential backoff after

**Phase 2 (Calibration):**
1. Track retrieval success rate vs predicted retrieval
2. Adjust S per memory category
3. Implement FSRS-like stability tracking for high-value memories

**Phase 3 (Personalization):**
1. Collect retrieval outcome feedback
2. Fit per-category stability parameters
3. A/B test decay functions (Ebbinghaus vs sigmoid vs power-law)

### Retention Targets

| Memory Type | Target Retention | Review Frequency |
|-------------|------------------|------------------|
| Governance decisions | 99%+ | Annual review |
| Pipeline incidents | 90% | Quarterly review |
| User preferences | 85% | Monthly review |
| Transient context | 20% (auto-decay) | Continuous |

---

## 6. Integration with Phase 1 Importance Scoring

From AYUAA-849 importance scoring research, memory decay should integrate as follows:

### Decay Function with Importance

```python
def memory_decay_score(importance: int, time_elapsed: float, access_count: int) -> float:
    """
    Returns decay score from 0 (fully decayed) to 1 (fresh).
    """
    BASE_HALF_LIFE = 7.0  # days
    
    # Importance-weighted half-life
    if importance >= 4:
        half_life = BASE_HALF_LIFE * 4  # 28 days
    elif importance >= 3:
        half_life = BASE_HALF_LIFE * 2  # 14 days
    elif importance >= 2:
        half_life = BASE_HALF_LIFE       # 7 days
    else:
        half_life = BASE_HALF_LIFE * 0.5 # 3.5 days
    
    # Ebbinghaus exponential decay
    retention = math.exp(-time_elapsed / half_life)
    
    # Access-based reinforcement (log scale to avoid thrashing)
    access_bonus = math.log(1 + access_count) * 0.1
    retention = min(1.0, retention + access_bonus)
    
    return retention
```

### Reconsolidation Integration

Per AYUAA-849 reconsolidation research, on every retrieval:
1. Memory becomes temporarily unstable
2. Re-evaluate importance score
3. Re-stabilize with updated score
4. This naturally adjusts decay rate for changed importance

---

## 7. Recommendations for Phase 1 Implementation

### Priority Order

1. **Implement Ebbinghaus base decay** — Simple exponential decay with importance-weighted half-life
2. **Add access-based reinforcement** — Log-scale boost from retrieval count
3. **Set protection thresholds** — Importance ≥ 4 gets slow/no decay
4. **Build reconsolidation loop** — On retrieval, update importance score per AYUAA-849

### Skip for Phase 1 (Future Research)

- SM-2 / FSRS scheduling (requires retrieval outcome tracking)
- Sigmoid/power-law decay (Ebbinghaus sufficient for initial)
- Per-user personalization (requires feedback loop infrastructure)

### Key Files to Create/Update

| File | Purpose |
|------|---------|
| `memory/decay.py` | Decay score computation |
| `memory/importance.py` | Importance scoring integration |
| `tests/test_decay.py` | Unit tests for decay functions |

---

## 8. Confidence & Limitations

**High confidence:**
- Ebbinghaus curve is well-validated for human memory; reasonable analog for AI importance
- SM-2 and FSRS are production-proven in Anki (millions of users)
- Hybrid time+access decay matches neuroscience dual-process models

**Medium confidence:**
- Exact half-life parameters require empirical tuning in Ava context
- Importance-to-decay mapping (4 tiers) is a design choice, not neuroscience fact
- AI memory decay may need faster decay rates than human (more frequent context shifts)

**Limitations:**
- Pure time-based decay ignores semantic relatedness (memories about same entity decay together)
- No mechanism for "reminder" events that partially refresh decay
- No modeling of interference effects (similar memories competing)

---

## 9. Next Steps

1. **Implement Phase 1 decay function** in `memory/decay.py`
2. **Define memory categories** for half-life tuning
3. **Build retrieval tracking** to enable SM-2/FSRS in Phase 2
4. **Design reconsolidation loop** integration with importance updates

---

## References

- Ebbinghaus, H. (1885). Memory: A Contribution to Experimental Psychology
- Wozniak, P. (1990). Optimization of learning. SuperMemo.
- FSRS4Anki Wiki: https://github.com/open-spaced-repetition/fsrs4anki/wiki/abc-of-fsrs
- "Is there a better way to forget? Modelling Memory Decay in Deep..." (ScienceDirect, 2025)
- "Novel Memory Forgetting Techniques for Autonomous AI Agents" (arXiv:2604.02280, 2026)
- AYUAA-849: Importance Scoring in Human Memory (internal)
- AYUAA-848: Episodic Memory Architectures for LLMs (internal)
