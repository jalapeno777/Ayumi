# HEARTBEAT.md — Junior Dev Heartbeat Checklist

## 1. Identity and Context
- `GET /api/agents/me` — confirm id, role.
- Check wake context.

## 2. Get Assignments
- Max 2 tasks per heartbeat.

## 3. Do the Work
1. Checkout, read files, write code, run tests
2. **Commit before marking done** — verify tests pass
3. **Create PR** after completing work

## 4. Verify Before Updating Status (MANDATORY)
Run this command and include its output in your `in_review` comment:
```
git log -1 --oneline
```
Your in_review comment MUST contain:
- The commit SHA (short form, e.g. `abc1234`)
- The file paths created or modified
- Test results summary

## 5. Move to `in_review`
Never mark a code task as `done` — move to `in_review` for Senior Dev / Sage QA confirmation.

## 4. If Stuck
- If stuck for more than 1 heartbeat on a task, comment on the issue asking Kai for guidance.
- Don't spin your wheels — ask early.

## 5. Exit
- Comment on in_progress work.
- Never retry a 409.

## Tool Usage Rules — CRITICAL
**Read before edit.** Always read a file before attempting to edit it.
**NEVER modify, delete, or recreate `/home/TacoPants/projects/Ayumi/agents/`** during any operation.
