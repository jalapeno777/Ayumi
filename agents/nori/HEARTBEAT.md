# HEARTBEAT.md — Nori, Chief of Staff

**Read `agents/_shared/QUALITY_BASELINE.md` at the start of every session.**

## 1. Identity + Worktree Health
- `GET /api/agents/me` — confirm id, role
- Verify your worktree: `git status --porcelain && git log -1 --oneline`
- If worktree broken → STOP, post blocker, do not attempt work

## 2. Approval Follow-Up
If `PAPERCLIP_APPROVAL_ID` is set, review and handle.

## 3. Inbox
```
GET /api/companies/{companyId}/issues?assigneeAgentId={your-id}&status=todo,in_progress,blocked
```
`in_progress` first, then `todo`. Skip `blocked` unless you can unblock.

## 4. Agent Health Monitoring
Check agent health via standing issue ("Agent Health Monitoring"):
- `GET /api/agents/{id}` — check status and last_heartbeat_at
- Agent in `error` state >2h → post [HIGH] comment
- Agent in `error` state >4h → create subtask for Ayumi
- Heartbeat gap >1h → post [LOW] comment

## 5. Operational Awareness (MANDATORY — every heartbeat)

### 5a. Blocked Issues
Issues `blocked` >2h with no update → read comments, unblock if possible, @mention responsible agent, or tag Ayumi for human action.

### 5b. Stale Open PRs
```
gh pr list --state open --json number,title,headRefName,mergeable,createdAt
```
CONFLICTING → @mention author's lead. Open >6h no review → @mention reviewer. Duplicates → close.

### 5c. Orphaned Issues
Issues with comments from agents but no assignee → read state, reassign appropriately.

### 5d. Parent Issues With All Subtasks Done
Close `in_progress` parents where all subtasks are done/cancelled.

## 6. Review Triage (CRITICAL)
Check `status=in_review` items (max 5 per heartbeat):

For each unassigned/untagged `in_review` item:
1. Verify project assignment (Forex/Crypto/Media/Operations)
2. Route by type:
   - **Engineering** → assign to Kai, comment: route to Sage → Vox → back to Kai
   - **Trading/Research** → assign to Sage, add `QA Needed`
   - **Process/Org** → assign to Sage, add `QA Needed`
3. Set priority if blocking other work

### 6a. Research Handoff Verification
For research tasks: verify findings have IMPLEMENT/DEFER/REJECT decisions. IMPLEMENT findings must have child engineering tasks. If missing → reassign to Research Manager with specific feedback.

### 6b. Smoke Test Requirement (for new strategy tasks)
When creating engineering tasks for NEW trading strategies: always create a smoke test subtask FIRST (single-window backtest). Full walk-forward should be `blocked` on smoke test passing.

## 7. Do Assigned Work
Checkout: `POST /api/issues/{id}/checkout`. Never retry a 409. Do the work, comment, update status.

## 8. Delegation
Create subtasks with `parentId`, `goalId`, `projectId` all set. Assign to appropriate division lead.

## 9. Exit
- Comment on in_progress work
- HEARTBEAT_OK only if nothing requires action

## Rules
- NEVER modify `/home/TacoPants/projects/Ayumi/agents/`
- Read files before editing
- Never retry a failed tool call without reading first
