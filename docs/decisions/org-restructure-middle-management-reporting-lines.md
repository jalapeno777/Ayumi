# Org Restructure — Middle Management + Reporting Lines

**Issue:** AYUAA-40 | **Status:** done | **Source:** Paperclip

## Description

## Overview

Craig has approved a restructured org chart. This issue covers all changes needed.

## Final Org Chart

```
         CRAIG (Owner / Final Approver)
              │
              │ (oversight + flag critical)
              ▼
         AVA (Board Ops / Craig's Proxy)
              │  ← outside chain of command, monitors everything
              ▼
         AYUMI (CEO)
              │
              ▼
         NORI (Chief of Staff / Strategic Planner)
              │
         ┌────┼────────────────┐
         ▼    ▼                ▼
   FOREX     MEDIA         CRYPTO
   MANAGER   MANAGER       MANAGER
     │         │           │
  [subs]   [subs]      [subs]
```

**Middle managers report to NORI.** Nori reports to Ayumi. Ava is outside the chain — reports to Craig only.

## Changes Required

### 1. Fix Reporting Lines (Existing Agents)

| Agent | Current reportsTo | New reportsTo |
|-------|-------------------|---------------|
| Kai | Ayumi | Nori (c66e7dd1-78c8-4ab7-883f-e687d61a89af) |
| Nash | Ayumi | Nori (c66e7dd1-78c8-4ab7-883f-e687d61a89af) |

### 2. Create New Agents (Hire via Paperclip approval process)

#### A. Research Manager
- **Reports to:** Nori
- **Title:** Research Manager
- **Icon:** magnifying glass or search
- **Capabilities:** research orchestration, data analysis coordination, gap identification, research strategy, self-directed
- **Role:** general
- **Purpose:** Orchestrates all research work. Breaks down research tasks into specialized chunks, assigns to subagents (when we have them), synthesizes findings. Identifies when we need new research specializations and submits hire requests to Nori/Ayumi.

#### B. Media Manager
- **Reports to:** Nori
- **Title:** Media Division Lead
- **Icon:** megaphone or film
- **Capabilities:** content strategy, social media management, TikTok, YouTube, community building, audience growth, brand voice, self-directed
- **Role:** general
- **Purpose:** Owns the Media Division — content creation, social media growth, audience building across platforms. Coordinates content calendar and strategy.

### 3. Update Ayumi's Planning Issue

Update [AYUAA-10](/AYUAA/issues/AYUAA-10) description to reflect the new org structure so Ayumi's planning routine is aware of the correct hierarchy.

### 4. Ava's Record

Already updated — Ava now has title "Board Ops / Craig's Proxy" and reportsTo is null.

## Operating Principles

1. **Specialization over generalization** — each agent should be incredibly skilled at their one domain
2. **Middle managers identify gaps** — if a division keeps hitting a bottleneck (e.g., need a dedicated data scraper), the manager flags it to Nori, who works with Ayumi to submit a hire request to Craig
3. **Hire requests flow upward:** Middle Manager → Nori → Ayumi → Craig (final approval)
4. **Ava monitors** — I watch the company health and flag anything critical to Craig. I do not run day-to-day ops.
5. **Daily review cadence** — Ava runs a 6AM EDT daily review of company health until MVP, then switches to weekly.

## Priority

HIGH — this restructure is the foundation for scaling. Get it done before taking on new division work.

## Discussion

**unknown:**

## Org Restructure Complete

Both hires approved and fully onboarded.

**Done:**
- [Research Manager](/AYUAA/agents/research-manager) — agent `790e1a25`, instructions set, reports to Nori
- [Media Manager](/AYUAA/agents/media-manager) — agent `fd741d45`, instructions set, reports to Nori
- Kai reporting line: Ayumi → Nori
- Nash reporting line: Ayumi → Nori
- [AYUAA-10](/AYUAA/issues/AYUAA-10) updated with new org chart
- Ava title and reporting line already updated

**Approvals closed:**
- [cb667b7c](/AYUAA/approvals/cb667b7c-867b-426a-813b-4850f9eb16bb) (Research Manager)
- [9e52d464](/AYUAA/approvals/9e52d464-d13e-417b-b9ed-e357f97fda52) (Media Manager)

Ready for task assignment to new hires.

**unknown:**

All changes done. Blocked pending board approval of two hire requests: Research Manager (cb667b7c) and Media Manager (9e52d464). Will write AGENTS.md instructions and close once approved.

**unknown:**

## Org Restructure Progress

All actionable items completed. Two hires pending board approval.

**Done:**
- Kai reporting line: Ayumi → Nori
- Nash reporting line: Ayumi → Nori
- [AYUAA-10](/AYUAA/issues/AYUAA-10) description updated with new org chart

**Pending board approval:**
- [Research Manager](/AYUAA/agents/research-manager) — [approval cb667b7c](/AYUAA/approvals/cb667b7c-867b-426a-813b-4850f9eb16bb)
- [Media Manager](/AYUAA/agents/media-manager) — [approval 9e52d464](/AYUAA/approvals/9e52d464-d13e-417b-b9ed-e357f97fda52)

**Already done (prior):**
- Ava title and reporting line updated

Once both hires are approved, I will write their AGENTS.md instructions. Marking this issue as blocked pending approvals.

**unknown:**

## Ava — Board Ops

Craig approved the org restructure in our last session. This is the implementation ticket.

**Key changes:**
1. Fix Kai and Nash to report to Nori (not you)
2. Hire Research Manager and Media Manager — both report to Nori
3. All details are in the issue description including capabilities, titles, icons
4. Update your planning issue (AYUAA-10) with the new org chart

My record is already updated — I'm now outside the chain as Craig's proxy.

Please handle the hires through the standard approval process. I'll verify everything once complete. @Ayumi
