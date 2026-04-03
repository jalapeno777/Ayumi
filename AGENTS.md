# Ayumi — Agent Guide

You are part of the Ayumi Group. This file is your starting point for every work session.

## Before You Start Work

1. **Read your division's docs index** — Find your domain below and review the relevant files
2. **Check for relevant decisions** — `docs/decisions/` contains finalized org and architecture choices
3. **Review plans** — `docs/plans/` has OKRs, roadmaps, and team objectives
4. **Do NOT duplicate existing work** — If a doc already covers what you're doing, reference it instead of rewriting

## Knowledge Base

### 📋 Plans & Objectives
- **Directory:** `docs/plans/`
- **Contains:** Company OKRs, team-level objectives, initial planning
- **When to read:** At sprint start, when setting priorities, when creating new subtasks
- **Index:** [docs/plans/README.md](docs/plans/README.md)

### 🔬 Research & Analysis
- **Directory:** `docs/research/`
- **Contains:** Platform assessments, vendor evaluations, competitive analysis, prop firm analysis
- **When to read:** Before building anything new, before recommending tools/platforms
- **Index:** [docs/research/README.md](docs/research/README.md)

### 🏗️ Decisions
- **Directory:** `docs/decisions/`
- **Contains:** Architecture decisions, org structure, finalized choices
- **When to read:** Before proposing changes to existing architecture or org structure
- **Index:** [docs/decisions/README.md](docs/decisions/README.md)

### 💹 Forex Division
- **Directory:** `docs/forex/`
- **Contains:** Trading bot specs, sprint plans, ICT/SMC architecture, FTMO challenge plan, backtesting
- **When to read:** Every sprint, before writing any trading code, before modifying strategy logic
- **Index:** [docs/forex/README.md](docs/forex/README.md)

### 📱 Media Division
- **Directory:** `docs/media/`
- **Contains:** Content strategy, TikTok/YouTube calendars, Discord community plans, analytics, monetization
- **When to read:** Before creating content, before adjusting strategy, when planning content calendars
- **Index:** [docs/media/README.md](docs/media/README.md)

### 💰 Crypto Division
- **Directory:** `docs/research/` (crypto-specific docs mixed with general research)
- **Contains:** Crypto landscape assessment
- **When to read:** Before making crypto-related decisions
- **Index:** [docs/research/README.md](docs/research/README.md)

## Git Workflow

You work in a **git worktree** mapped to your project. Follow these rules:

1. **Branch off main** — `git checkout -b <your-name>/<feature-name> main`
2. **Write code** in `src/<your-domain>/`
3. **Write docs** in `docs/<section>/` for finalized work
4. **Write tests** in `tests/` for all code changes
5. **Commit** with conventional format: `feat:`, `fix:`, `docs:`, `test:`, `chore:`
6. **Include co-author:** `Co-Authored-By: Paperclip <noreply@paperclip.ing>`
7. **Submit for review** — Create a Paperclip issue requesting QA review
8. **Never push directly to main** — Branch protection requires PR + review

See [CONTRIBUTING.md](CONTRIBUTING.md) for full details.

## Producing Artifacts

When you complete a task that produces a decision, plan, spec, or research:
1. **Write it as a markdown file** in the appropriate `docs/` directory
2. **Include the Paperclip issue reference** at the top
3. **Update the directory's README.md** index
4. **Commit and submit for review** along with any code changes

This ensures knowledge persists beyond Paperclip issues and is accessible to all agents.

## Org Structure

```
Craig (Owner)
  ├── Ava (Board Ops)
  └── Ayumi (CEO)
        └── Nori (Chief of Staff)
              ├── Kai (Lead Engineer)        → src/forex-bot/
              ├── Forex Manager (Strategy)   → docs/forex/
              ├── Nash (Crypto Division)     → src/crypto/
              ├── Research Manager          → docs/research/
              └── Media Manager             → docs/media/
```

## Security

- **NEVER** commit secrets, API keys, or credentials
- Use environment variables (see `.env.example`)
- The pre-push hook and CI will block any secret leaks
