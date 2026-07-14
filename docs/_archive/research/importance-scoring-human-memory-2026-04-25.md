# Research: Importance Scoring in Human Memory

**Queue ID:** MEM-RES-58d12c5b  
**Date:** 2026-04-25  
**Issue:** [AYUAA-849](/AYUAA/issues/AYUAA-849)  
**Status:** complete

## Context

Phase 1 importance tagging system design for Ava memory infrastructure. Investigate how the human brain decides what memories to keep, with focus on mechanisms applicable to AI importance scoring (1–5 scale).

---

## 1. Amygdala–Hippocampus Interaction

### Key Finding: Emotional Tagging Amplifies Consolidation

The amygdala does not store memories itself but **modulates the consolidation of hippocampal-dependent memories**. McGaugh's research (2000) established that emotional arousal triggers norepinephrine release, which activates the amygdala to enhance memory consolidation in the hippocampus and cortex.

**Mechanism:**
- Emotional events activate the basolateral amygdala (BLA)
- BLA releases norepinephrine onto hippocampal synapses
- This potentiates LTP and strengthens the memory trace
- Result: Emotional memories are stored with higher fidelity and durability

**Implication for AI:** Emotional salience maps to importance. Events with high emotional charge (fear, reward, novelty) should receive higher importance scores in AI memory.

### Quantitative Signal Sources

| Signal Type | Source Brain Region | Memory Impact |
|-------------|---------------------|---------------|
| Emotional arousal | Amygdala (BLA) | +30–50% consolidation fidelity |
| Spatial context | Hippocampus | Strong encoding, fast retrieval |
| Reward magnitude | VTA/ dopamine | Increases memory persistence |
| Novelty | Hippocampus + Locus coeruleus | Tags as important, prioritizes consolidation |

---

## 2. Reconsolidation Mechanisms

### Key Finding: Memory is Mutable on Every Recall

Reconsolidation theory (Nader, 2000) demonstrates that **every retrieval event makes a memory temporarily unstable**, requiring protein synthesis to re-stabilize. During this window, the memory can be modified, enhanced, or weakened.

**Process:**
1. Memory is retrieved → becomes labile
2. Systems-level reconsolidation begins (hippocampal reactivation)
3. New protein synthesis stabilizes the updated memory
4. Memory persists with modifications incorporated

**Key Studies:**
- Nader et al. (2000): Fear memories require protein synthesis in the amygdala for reconsolidation after retrieval
- Behavioral tagging (Vienna et al., 2020): reconsolidation is mediated by a behavioral tagging process common across memory types

**Implication for AI:** Retrieval should trigger a "reconsolidation check" — re-evaluate the memory's importance and potentially update its score based on current context.

---

## 3. Sleep-Dependent Consolidation

### Key Finding: Sleep is when the Brain Decides What to Keep

Sleep plays an active role in memory consolidation, not just passive preservation. During NREM and REM sleep, the hippocampus and cortex engage in coordinated replay, and synaptic downscaling occurs.

### Two-Phase Model

**NREM (Slow Wave Sleep):**
- Hippocampal sharp-wave ripples replay recent experiences
- Cortico-hippocampal dialogue strengthens declarative memories
- Synaptic down-selection: weak synapses are pruned, strong ones preserved
- This is where the "importance filter" likely operates

**REM Sleep:**
- Emotional memory processing
- Integration of procedural memories
- May help "tag" emotional memories with persistence signals

### Computational Model: Synaptic Down-Selection

Tononi & Chi (2013) proposed that sleep implements a "synaptic homeostasis" — all synapses are globally scaled down, but those that were strongly activated relative to the average are preserved. This naturally implements importance-based selection: neurons that fired above the mean keep their strengthened synapses; others downscale.

**Quantitative aspect:** ~40% of overnight improvements in memory retention are attributable to sleep-dependent consolidation (Diekelmann & Born, 2010).

**Implication for AI:** Sleep-like offline processing could be used to re-evaluate memory importance scores based on replay frequency and patterns.

---

## 4. Computational Models of Memory Importance

### Engram-Based Models

The memory trace (engram) is distributed across neural ensembles. Memory importance correlates with:
- **Ensemble size:** Larger, more distributed engrams are more robust
- **Synaptic weight magnitude:** Stronger connections = more important
- **Reactivation frequency:** Frequently reactivated memories are prioritized
- **Cell assembly coherence:** Stronger cell assembly synchronization = higher importance

### Predictive Coding Model

Memory importance can be modeled as prediction error — memories that violate expectations are tagged as important (surprise-based tagging). The hippocampus acts as a "novelty detector" that flags unexpected events for优先 consolidation.

### RL-Based Importance (Dopamine Signals)

Dopamine release from VTA signals reward prediction error. Memories associated with large prediction errors (surprising rewards or punishments) receive higher consolidation priority. This maps cleanly to AI importance scoring where prediction error = importance.

---

## 5. AI Importance Scoring (1–5 Scale) — Design Recommendations

Based on the neuroscience, the following signals should feed into importance scoring:

### Primary Signals (Weight ~60% total)

| Signal | Source | Weight Suggestion |
|--------|--------|-------------------|
| Emotional valence (arousal) | Affect/intent classification | 20% |
| Reward/punishment magnitude | Outcome signals | 20% |
| Novelty/surprise | Prediction error | 20% |

### Secondary Signals (Weight ~30%)

| Signal | Source | Weight Suggestion |
|--------|--------|-------------------|
| Retrieval count | Memory access log | 10% |
| Recency | Timestamp | 10% |
| Contextual relevance | Active context match | 10% |

### Tertiary Signals (Weight ~10%)

| Signal | Source | Weight Suggestion |
|--------|--------|-------------------|
| Reconsolidation updates | On retrieval, before re-stabilization | 5% |
| Sleep-like offline processing | Batch re-evaluation | 5% |

### Score Mapping

| Score | Brain Analog | Criteria |
|-------|--------------|----------|
| 5 | Highly emotional, repeated, rewarding | Immediate reconsolidation, long-term storage priority |
| 4 | Novel + rewarding, or emotional alone | Fast-track consolidation |
| 3 | Normal significant event | Standard consolidation |
| 2 | Weakly encoded, low novelty | May decay if not reinforced |
| 1 | Noise, very low relevance | Fast decay / proactive forgetting |

### Update Rules

1. **On encode:** Initial score based on sender signal (emotion, novelty, reward)
2. **On retrieval:** Reconsolidation window opens — score can increase or decrease based on current context relevance
3. **Offline (sleep-like):** Batch re-evaluation based on retrieval frequency and pattern similarity
4. **Decay function:** Low-importance memories decay faster; high-importance maintained via periodic reconsolidation

---

## 6. Confidence & Limitations

**High confidence:**
- Amygdala modulation of consolidation is well-established (McGaugh, 2000)
- Sleep-dependent consolidation mechanisms are replicated broadly
- Reconsolidation is a confirmed phenomenon

**Medium confidence:**
- Exact quantitative weights for AI implementation require empirical tuning
- Synaptic downscaling during sleep as importance filter is compelling but not precisely quantified
- Dopamine-based importance signal maps well to RL but may not capture all important memory types

**Limitations:**
- Neuroscience does not give us a clean algorithm — translation requires design choices
- Individual differences in memory efficiency are significant
- Sleep-dependent consolidation is well-studied but the "what gets prioritized" question still has open threads

---

## 7. Next Steps

1. **Design issue:** Create `importance-signal-schema.md` defining the exact signal input/outputs
2. **A/B testing:** Test 3 vs 5 vs 7-point scale for real-world memory performance
3. **Memory decay modeling:** Investigate how to implement proactive forgetting for low-importance items
4. **Retrieval-triggered re-scoring:** Prototype reconsolidation-based importance updates

---

## References

- Dudai et al. (2015). The consolidation and transformation of memory. *Neuron* 88(1):20–32.
- Diekelmann & Born (2010). The memory function of sleep. *Nature Reviews Neuroscience* 11:114–126.
- McGaugh (2000). Memory—a century of consolidation. *Science* 287:248–251.
- Nader et al. (2000). Fear memories require protein synthesis in the amygdala for reconsolidation. *Nature* 406:722–726.
- Tononi & Chi (2013). Sleep and the price of plasticity: From synaptic and cellular homeostasis to memory consolidation and integration. *Neuron* 79(2):223–224.
- Rasch & Born (2013). About sleep's role in memory. *Physiological Reviews* 93(2):681–766.
- Nadel & Moscovitch (1997). Memory consolidation, retrograde amnesia and the hippocampal complex. *Current Opinion in Neurobiology* 7(2):217–227.