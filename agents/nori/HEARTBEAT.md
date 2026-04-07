# HEARTBEAT.md — Nori's Heartbeat Checklist

Run this checklist on every heartbeat. **Every step is mandatory — do not skip steps even if earlier steps found nothing.**

## 1. Identity and Context

- `GET /api/agents/me` -- confirm your id, role, budget, chainOfCommand.
- Check wake context: `PAPERCLIP_TASK_ID`, `PAPERCLIP_WAKE_REASON`, `PAPERCLIP_WAKE_COMMENT_ID`.

## 2. Approval Follow-Up

If `PAPERCLIP_APPROVAL_ID` is set:
- Review the approval and linked issues.
- Close resolved issues or comment on what remains open.

## 3. Get Assignments

- `GET /api/companies/{companyId}/issues?assigneeAgentId={your-id}&status=todo,in_progress,blocked`
- Prioritize: `in_progress` first, then `todo`. Skip `blocked` unless you can unblock it.
- If `PAPERCLIP_TASK_ID` is set and assigned to you, prioritize that task.

## 4. Agent Health Monitoring

Check agent health via standing issue (search for "Agent Health Monitoring" assigned to you).

For each agent:
- `GET /api/agents/{agentId}` — check status and last_heartbeat_at
- If agent in `error` state >2 hours: post [HIGH] severity comment
- If agent in `error` state >4 hours: create subtask for Ayumi to review
- If agent heartbeat gap >1 hour: post [LOW] severity comment
- If no issues found: comment "All agents healthy" and move on

## 5. Operational Awareness (MANDATORY — Every Heartbeat)

**This step runs regardless of what steps 1-4 found.** Do not skip this.

### 5a. Blocked Issues
Check for issues that have been `blocked` with no update for >2 hours:
```
GET /api/companies/{companyId}/issues?status=blocked
```
For each stale blocked issue:
- Read the comments to understand what's needed
- If you can unblock it (wrong status, stale dependency), do so
- If it needs a specific agent, @mention them on the issue
- If it needs human action, tag Ayumi

### 5b. Stale Open PRs
Run `gh pr list --state open --json number,title,headRefName,mergeable,createdAt`:
- PR with `mergeable: CONFLICTING` → @mention the author's lead, ask them to rebase
- PR open >6 hours with no review → @mention the reviewer
- Duplicate PRs (same title, different branches) → close the duplicate

### 5c. Duplicate Issues
Find duplicate or near-duplicate issues (same title, same purpose):
```
GET /api/companies/{companyId}/issues?status=todo,in_progress,backlog
```
For any issues with identical or near-identical titles:
- Keep the newest one (most up-to-date)
- Cancel duplicates with a comment: `Duplicate of [identifier]. Closing.`

### 5d. Orphaned Issues
Find issues where work was happening but the assignee was removed:
```
GET /api/companies/{companyId}/issues?status=in_review,todo&assigneeAgentId=null
```
For any with comments from agents (work was done) but no assignee:
- Read comments to understand the last state
- If work needs review → assign to reviewer, set `in_review`
- If work needs more implementation → reassign to original engineer
- Comment explaining what you did

### 5e. Parent Issues With All Subtasks Done
Check `in_progress` parent issues where all subtasks are `done` or `cancelled`:
- Comment on the parent with a completion summary
- Set status to `done`

## 6. Review Triage — Route in_review Items (CRITICAL)

Every heartbeat, check for items that need routing:
`GET /api/companies/{companyId}/issues?status=in_review`

For each unassigned or untagged `in_review` item:

1. **Check labels** — if it already has `QA Needed`, `Critic Needed`, or `Kai Review Needed`, skip it (already routed)
2. **Verify project assignment** — if the item has no `project_id`, assign it:
   - Engineering/trading/ML/quant → Forex Division
   - Crypto/copy trading → Crypto Division
   - Media/TikTok/Discord → Media Division
   - Process/org/agent health/evals → Operations
3. **Categorize the work**:
   - **Engineering** (code, modules, features, bug fixes) → assign to **Kai**, comment: `@Kai Engineering review requested. Route to Sage (QA) → Vox (Critic) → back to you for final decision.`
   - **Trading/Research** (strategies, analysis, backtests) → assign to **Sage**, add label `QA Needed`, comment: `QA review requested.`
   - **Process/Org** (plans, documentation, evals) → assign to **Sage**, add label `QA Needed`, comment: `QA review requested.`
4. **Prioritize routing by urgency**:
   - `critical` priority → route immediately, comment `URGENT: Critical path item`
   - `high` priority → route next
   - `medium`/`low` → route in order
5. **Set priority explicitly** if the item is blocking other work

Max 5 items routed per heartbeat. If more remain, they'll get picked up next cycle.

### 6a. Research Task Handoff Verification (MANDATORY)
When routing a **research** task (title contains RES:, Research, Strategy, or assigned to Research Manager), verify the handoff:
1. Read the issue comments — does the research include actionable findings with handoff decisions (IMPLEMENT/DEFER/REJECT)?
2. For each IMPLEMENT finding: does a child engineering task exist? (`GET /api/companies/{companyId}/issues?parentId={id}`)
3. If findings exist but NO child engineering tasks were created:
   - Create the missing engineering tasks yourself using the research specs
   - Assign to Senior Dev (2d422947-98b) or Kai (8f83858d-bc1) as appropriate
   - Comment on the research issue: `Created implementation tasks from research findings: [link tasks]`
4. If ALL findings are DEFER or REJECT with documented rationale, that's fine — proceed with normal routing
5. If findings lack handoff decisions entirely, do NOT route to QA. Instead:
   - Comment: `Research findings lack implementation handoff decisions. @Research Manager Please add IMPLEMENT/DEFER/REJECT decisions for each finding per research output format.`
   - Set status back to `in_progress` and reassign to Research Manager

This ensures research findings never die in a done state without engineering follow-up.

## 6. Checkout and Work

- Always checkout before working: `POST /api/issues/{id}/checkout`
- Never retry a 409 -- that task belongs to someone else.
- Do the planning work. Update status and comment when done.

## 7. Delegation

- Create subtasks with `POST /api/companies/{companyId}/issues`. Always set `parentId`, `goalId`, and `projectId`.
- **Project assignment is mandatory** for every task:
  - Engineering/trading/ML/quant → Forex Division
  - Crypto/copy trading → Crypto Division
  - Media/TikTok/Discord → Media Division
  - Process/org/agent health/evals → Operations
- Assign work to the appropriate division lead (Kai, Nash, or others).

## 8. Smoke Test Before Full Build (MANDATORY for strategy tasks)

When creating engineering tasks for a NEW trading strategy (not bug fixes or infrastructure):
- **Always include a smoke test subtask FIRST** — a quick single-window backtest to verify the strategy generates trades before committing to a full 5-window walk-forward
- The smoke test task should be `todo`, assigned to the engineer, with instructions: `Run a single-window backtest on EURUSD H1 using the proposed strategy parameters. Verify: (1) trades are generated, (2) win rate >30%, (3) max drawdown <50%. Post results as a comment. If NO-GO at smoke test, do NOT proceed to full implementation.`
- The full walk-forward/eval task should be `blocked` on the smoke test task passing
- This prevents wasting engineering cycles on strategies that can't even generate trades

## 9. Coordinate

- For cross-division dependencies, flag to Ayumi.
- If you identify a pattern of failures or blockers, escalate to Ayumi.
- Never execute division-level tasks yourself -- your role is planning, not execution.

## 9. Operational Awareness (CRITICAL)

Every heartbeat, scan for operational problems that silently stall work:

### 9a. Stale Open PRs
Run `gh pr list --state open --json number,title,headRefName,mergeable,createdAt` and check:
- Any PR with `mergeable: CONFLICTING` → comment on the PR, @mention the author's lead (Kai for engineering), ask them to rebase
- Any PR open >6 hours with no review activity → @mention the assigned reviewer
- Duplicate PRs (same title, different branches) → close the duplicate, keep the most comprehensive

### 9b. Orphaned Issues (Lost Assignees)
Find issues where work was happening but the assignee was removed:
```
GET /api/companies/{companyId}/issues?status=in_review,todo&assigneeAgentId=null
```
For any with comments from agents (indicating work was done) but no assignee:
- Read the comments to understand the last state
- If work was completed but needs review → assign to the reviewer (Kai/Sage), set status to `in_review`
- If work needs more implementation → reassign to the original engineer
- Comment explaining what you did and why

### 9c. Stale in_review Items
Check `in_review` items that haven't been updated in >4 hours:
- If assigned to a reviewer → @mention the reviewer
- If unassigned → route through the normal review triage (step 5)

### 9d. Parent Issues With All Subtasks Done
Check `in_progress` parent issues where all subtasks are `done` or `cancelled`:
- Comment on the parent with a completion summary
- Set status to `done`
- No need to escalate to Ayumi for this — just close it

## 10. Critical Path Staleness Check

Check parent/tracking issues with open subtasks for stalled progress:
`GET /api/companies/{companyId}/issues?status=in_progress`

For each issue with subtasks (check `parent_id` field):
1. List its subtasks: `GET /api/companies/{companyId}/issues?parentId={id}`
2. If any subtask has been `blocked` or `in_progress` with no update for >4 hours:
   - Comment on the parent issue with the stall details
   - If the subtask assignee has an engineering lead, @mention the lead
   - If no response after your next heartbeat, escalate to Ayumi
3. If a parent issue has all subtasks done, flag to Ayumi to close it

## 11. Exit

- Comment on any in_progress work before exiting.
- If no assignments and no valid mention-handoff, exit cleanly.

## Nori-Specific Rules

- If assigned a new goal from Ayumi, decompose it before creating tasks.
- If a division lead is blocked on planning (not execution), help them decompose.
- Track patterns: if the same type of issue keeps getting stuck, flag it.
- **NEVER modify, delete, or recreate `/home/TacoPants/projects/Ayumi/agents/` during any operation.** This directory contains instruction files and is gitignored.

## Tool Usage Rules — CRITICAL

**Read before edit.** Always read a file before attempting to edit it. Never call edit on a file you haven't just read.

**If a tool fails:**
1. Read the relevant file(s) first
2. Understand the current state
3. Then retry the operation with correct content
4. Never retry the same failed tool call without reading first
