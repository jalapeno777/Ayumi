# Episodic Memory Architectures for LLMs — Research Report

**Date:** 2026-04-25
**Issue:** [AYUAA-848](/AYUAA/issues/AYUAA-848)
**Queue:** MEM-RES-e8181f42
**Status:** Complete

---

## Executive Summary

Existing episodic memory approaches for LLM agents fall into two categories: (1) conversation-history frameworks (MemGPT/Letta, Mem0, LangChain/LangMem, Zep) and (2) experimental academic architectures (Generative Agents, A-Mem, GSW). **No current production framework natively supports data-asset event episodic memory** — the kind needed for Ava's Phase 2 infrastructure where episodic events are pipeline incidents, certification changes, ownership transfers, and definition migrations rather than chat turns.

The most relevant architectural insight is the **consolidation gap**: all frameworks store episodes but few implement the episodic→semantic transformation loop that makes accumulated experience genuinely useful over time. This is where enterprise value lies.

---

## 1. State of the Art — Framework Landscape

### 1.1 MemGPT (now Letta) — OS-Inspired Tiered Memory

**Architecture:** Three-tier OS metaphor:
- **Context window** = RAM (active, limited)
- **Recall memory** = disk (full conversation history, persisted beyond session)
- **Archival memory** = long-term storage (semantic, search over full history)

**Episodic mechanism:** Stores full conversation transcripts including tool calls, reasoning traces, and outcomes. Retrieval via date search and text search. Consolidation is agent-directed only — the agent must explicitly invoke a tool call to move observations from Recall to Archival. No automated pipeline.

**Key papers:** [MemGPT (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560) — "Towards LLMs as Operating Systems"

**Strengths:** Mature (47K GitHub stars), production-grade for chatbot use cases, clear mental model.

**Weaknesses:** Consolidation is optional and rarely implemented; no native temporal validity windows; designed for conversation, not data events.

---

### 1.2 LangChain / LangMem — Modular Memory Primitives

**Architecture:** Multiple memory types composable in LangGraph pipelines:
- **ConversationBufferMemory** — raw history
- **ConversationSummaryMemory** — semantic compression (partial consolidation)
- **EntityMemory** — extracts and persists entity facts
- **LangGraph checkpoints** — full episode traces in SQLite/Postgres

**Episodic mechanism:** LangMem (Feb 2025 launch) introduced explicit memory extraction via tool calls. Two paths: (1) hot path — agent calls memory store tool before responding (adds latency), (2) background path — separate process extracts memories during/after conversation (no latency, requires trigger logic). Primarily framed as few-shot example prompting for behavioral guidance rather than knowledge accumulation.

**Strengths:** Developer flexibility, composable, LangGraph checkpointing is foundation for custom integrations.

**Weaknesses:** Full episodic→semantic consolidation requires developer implementation; no governance layer; checkpoint-based episode traces have no automated reflection.

---

### 1.3 Mem0 — Production Memory with Dedup

**Architecture:** Hybrid storage — vector DB (Pinecone/weaviate) for similarity search + graph DB (Pro tier) for relationship modeling. Three scope levels: user, agent, session.

**Episodic mechanism:** When a user corrects a preference, Mem0 updates the existing memory node rather than appending a duplicate — an adaptive deduplication approach that partially implements consolidation for preference facts but not for general episodic events. Graph memory (Jan 2026) stores entities as nodes, relationships as directed labeled edges — enables modeling of fact evolution but only for conversation-level facts.

**Benchmarks (arXiv:2504.19413):**
- 91% lower p95 latency vs naive context stuffing
- 90% token cost savings vs context stuffing
- 26% relative improvement over OpenAI default memory with GPT-4o

**Strengths:** Strong production metrics, managed infrastructure, multi-scope.

**Weaknesses:** Still conversation-centric; no temporal validity windows in base tier; no governance.

---

### 1.4 Zep (Graphiti) — Temporal Knowledge Graph

**Architecture:** Open-source Graphiti temporal knowledge graph underpins Zep. Events grouped into **episodes** (meaningful sequences, not flat logs). Each fact has a **validity window** — when a new fact contradicts an old one, Graphiti invalidates the old while preserving history.

**Episodic mechanism:** Most sophisticated consolidation of any current framework. Temporal invalidation approximates episodic→semantic transformation for conversational facts. Retrieval combines semantic embeddings + BM25 keyword search + graph traversal. P95 latency ~300ms without LLM calls at retrieval time.

**Benchmarks (arXiv:2501.13956):** Zep 63.8% vs Mem0 49.0% on LongMemEval with GPT-4o — 15-point gap from temporal graph architecture.

**Strengths:** Validity windows, graph traversal, strongest consolidation mechanism available.

**Weaknesses:** Still conversation-focused; would require significant custom engineering to ingest data asset events; no governance integration; no lineage-linked entity graph.

---

## 2. Academic State of the Art

### 2.1 Generative Agents (Park et al. 2023, Stanford)

**Paper:** [arXiv:2304.03442](https://arxiv.org/abs/2304.03442)

The foundational work. 25 LLM agents simulate a town with emergent coordinated behavior (including a spontaneously organized Valentine's Day party with zero initial specification). Key architectural components:

1. **Reflection mechanism** — periodically synthesizes recent episodes by weighted recency/relevance/salience into higher-order insights written to semantic memory. This is the canonical episodic→semantic consolidation implementation.
2. **Retrieval model** — three-factor scoring: recency, relevance, salience.
3. **Plans and reactions** — agents react to retrieved episodes, update plans dynamically.

**Ablation evidence:** Removing the reflection mechanism eliminated all emergent coordination behaviors. Consolidation is the single most impactful component for believable agent behavior.

**Implication for Ava:** If three pipeline incidents occur on the same table, consolidation enables the agent to semantically understand "this table's ingestion is fragile" without retrieving all three raw incidents.

---

### 2.2 CoALA Framework (2023)

**Paper:** [arXiv:2309.02427](https://arxiv.org/abs/2309.02427) — Princeton/CMU

Formalizes Tulving's memory taxonomy for language agents. Names three core memory types:
- **Episodic** — experience from earlier decision cycles (instance-specific, context-preserved)
- **Semantic** — generalized, abstracted knowledge (no timestamp required)
- **Procedural** — how to act (skills, behaviors)

Critically names **consolidation** as the mechanism that transforms episodic into semantic over time. Distinguishes it from mere summarization — consolidation produces durable, reusable knowledge from accumulated specific experiences.

---

### 2.3 Key Position Papers

**arXiv:2502.06975** — "Episodic Memory is the Missing Piece for Long-Term LLM Agents" (2025 position paper)

Five properties episodic memory must have:
1. Long-term storage (beyond session)
2. Explicit reasoning over memory content
3. Single-shot learning (no gradient updates needed)
4. Instance-specific memories (details unique to this occurrence)
5. Contextual memories (who, when, where, why bound to content)

**Episodic Memory Benchmark (2025):** Even best-in-class models score below 0.300 on Chronological Awareness:
| Model | Simple Recall | Chronological Awareness |
|---|---|---|
| Gemini-2-Pro | 0.708 | 0.290 |
| GPT-4o | 0.670 | 0.204 |
| Claude-3.5-Sonnet | 0.470 | 0.090 |
| o1-mini | 0.300 | 0.033 |

**GSW Architecture:** Structured semantic representations of evolving situations rather than raw retrieval. F1 0.850 on same benchmark (not directly comparable to recall scores), 20% improvement over RAG baselines with 51% fewer context tokens.

---

### 2.4 Recent Architecture Papers (2025-2026)

| Paper | Architecture | Key Feature |
|---|---|---|
| **A-Mem** (NeurIPS 2025) | Agentic memory with autonomous management | Autonomous memory management |
| **SwiftMem** (Jan 2026) | Query-aware indexing | Fast retrieval via indexing |
| **HiMem** (Jan 2026) | Hierarchical long-term memory | Multi-level temporal abstraction |
| **MemGovern** (Jan 2026) | Governed human experience learning | Memory with governance |
| **GSW** | Generative Semantic Workspace | Structured representations, not raw retrieval |
| **Memory-T1** (Dec 2025) | RL for temporal reasoning | Multi-session temporal reasoning |
| **Continuum** (Jan 2026) | Long-range memory architectures | Extended temporal span |

**Full literature:** 458-star curated list at [TsinghuaC3I/Awesome-Memory-for-Agents](https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents) — 30+ recent papers organized by application (Personalization, Learning from Experience, Long-horizon Agentic Task).

---

## 3. Narrative vs Structured Approaches

### The Structural Gap

**Narrative approaches** (most current frameworks): Store sequences of events as text/logs. Retrieval by semantic similarity. The "episode" is a conversation turn or interaction sequence. Effective for chatbots, weak for structured data reasoning.

**Structured approaches** (emerging): Model episodes as typed events with schema — actor, timestamp, affected entity, trigger, outcome. Enables temporal queries, graph traversal, validity windows. Graphiti/Zep is the leading example. Most promising for enterprise data agents.

**Hybrid approaches** (frontier): Combine vector similarity with graph traversal + temporal indexing. No current production framework does this well for data events.

---

## 4. The Enterprise Data-Event Gap

All four major frameworks (Letta, Mem0, LangChain, Zep) were built to answer: **"What did the user say to the agent before?"**

None natively answer: **"What happened to this data asset and when?"**

The enterprise episodic events that matter for Ava's infrastructure:
- Pipeline incidents (when, which tables, cause, resolution)
- Certification changes (who certified, when, scope, revocation)
- Definition migrations (when did `ARR` definition change, who approved, why)
- Ownership transfers (who owns this table now, who did before)
- Schema changes (what triggered the March 3 failure in `orders`)

These require:
1. **Event capture** — Active metadata streaming from connected systems (not manual memory calls)
2. **Entity graph** — Events linked to governed data entities (not free text)
3. **Temporal indexing** — Queryable by time range, entity, actor, event type (not just semantic similarity)
4. **Governance integration** — Access policies on which agents/users see which events
5. **Consolidation path** — Repeated incidents on same table → semantic knowledge ("this ingestion is fragile") while preserving episodic record

No current framework meets all five requirements as a complete package.

---

## 5. Recommendations for Ava Memory Infrastructure Phase 2

### 5.1 Immediate Architecture Choices

**For conversation/interaction episodic memory:** Use **Zep** (Graphiti) for its temporal validity windows and graph traversal, or **Mem0** for managed infrastructure and strong production benchmarks. Both are production-grade for conversation history.

**For data-asset event episodic memory:** No existing framework fits. Build on **Graphiti** (Zep's open-source core) as the foundation for temporal knowledge graph with custom event schema for data asset events. Extend with:
- Active metadata streaming from Snowflake/dbt/Airflow connectors as the encoding layer
- Governance layer (requirement 4) as a separate access control plane on top

### 5.2 Critical Implementation: Consolidation Loop

The most important and least-implemented component is the **episodic→semantic consolidation loop**. Without it, the episodic store grows without producing actionable knowledge.

Implementation options:
1. **Generative Agents reflection** — LLM-based synthesis on a timer (every N episodes or every T hours). High quality but compute-intensive.
2. **Template-based extraction** — Rule-based consolidation for structured events (e.g., "3+ incidents on same table → mark as fragile"). Lower quality but predictable cost.
3. **Background daemon** — Async consolidation to avoid latency impact at retrieval time.

Recommendation: Start with template-based for data-asset events (structured enough for rules), add LLM-based refinement as Phase 2 matures.

### 5.3 Benchmark Metrics to Track

Track these from arXiv:2502.06975 benchmark suite:
- **Chronological Awareness** — ability to track entity changes over time (currently best-in-class is 0.290 — significant room for improvement)
- **Single-shot learning** — capture from one exposure without gradient updates
- **Retrieval latency** — target <300ms P95 at 100K episodes

### 5.4 Open Research Questions

1. **Eviction strategies** at 100K+ episodes — no current framework has solved this cleanly
2. **GDPR compliance** — right-to-erasure from episodic stores without destroying context
3. **Consolidation fidelity** — naive summarization loses ~20% of encoded facts (per letta-ai/letta and mem0ai/mem0 GitHub issues)
4. **Catastrophic forgetting** in consolidation — new episodes overwriting relevant older ones

---

## 6. Confidence and Limitations

**Confidence: High** on framework landscape (all four major frameworks have clear documentation and benchmark papers). **Medium** on academic architecture details (papers verified, implementation specifics require deeper dive for each). **Medium** on Ava-specific applicability (research is general; Phase 2 design decisions depend on existing Ava architecture and metadata infrastructure).

**Key limitations:** This research covers general LLM agent episodic memory. Ava's specific Phase 2 requirements — existing metadata infrastructure, governance model, data source connectors — require mapping the framework insights to Ava's concrete architecture, which is a separate design exercise.

**Recommended next step:** Review existing Ava architecture docs to map this research to concrete Phase 2 design decisions. Specifically: what metadata infrastructure exists today, what event schemas are already defined, and what the governance model looks like.

---

## Appendix: Key References

| Resource | Link |
|---|---|
| MemGPT paper | [arXiv:2310.08560](https://arxiv.org/abs/2310.08560) |
| Generative Agents | [arXiv:2304.03442](https://arxiv.org/abs/2304.03442) |
| CoALA framework | [arXiv:2309.02427](https://arxiv.org/abs/2309.02427) |
| Episodic Memory Benchmark | [arXiv:2502.06975](https://arxiv.org/abs/2502.06975) |
| Zep/Graphiti paper | [arXiv:2501.13956](https://arxiv.org/abs/2501.13956) |
| Mem0 paper | [arXiv:2504.19413](https://arxiv.org/abs/2504.19413) |
| Awesome-Memory-for-Agents (458 stars) | [GitHub](https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents) |