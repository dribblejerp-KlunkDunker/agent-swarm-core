# Task Board

This file is the live task registry for the swarm.

Use one block per task.

```text
Task ID: <task-id>
Title: <short task name>
Status: INTAKE | GROUNDED | PLANNED | READY | IN_PROGRESS | VERIFYING | READY_FOR_RELEASE | AWAITING_APPROVAL | RELEASED | BLOCKED | CANCELLED | CLOSED
Owner: <agent or human>
Primary Skill: <skill name>
Complementary Skills: <skill names>
Repository: <repo name>
Branch: <branch>
Base Revision: <commit or branch>
Task Request: <one-line request>
Objective: <what success looks like>
In Scope:
- <item>
Out of Scope:
- <item>
Acceptance Criteria:
- [ ] <criterion>
Evidence Required:
- <artifact or command>
Reserved Files / Resources:
- <resource>
Blockers:
- <none or blocker>
Risk Level: LOW | MEDIUM | HIGH | CRITICAL
Approval Required: YES | NO
Approved By: <person or team>
Last Handoff: <agent -> agent or none>
Updated At: <timestamp>
```

## Current board state

No tasks are active by default. Add tasks here as they are created.
