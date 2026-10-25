# Lock and Coordination Model

This file defines how the swarm prevents conflicting edits and enforces task coordination.

## Purpose

The swarm must avoid parallel destructive or conflicting edits. The lock model is the coordination layer that prevents tasks from silently overwriting each other.

## Core rule

No two active tasks may hold overlapping resource locks for the same file, directory, or critical dependency without explicit orchestration.

## Lock types

- file lock
- directory lock
- environment lock
- tool lock
- dependency lock

## Lock schema

```text
lock_id:
resource:
resource_type: file | directory | environment | tool | dependency
owner:
task_id:
status: ACTIVE | RELEASED | EXPIRED
reason:
acquired_at:
released_at:
```

## Lock acquisition protocol

Before implementation or validation, the task must reserve the relevant resources.

Required steps:
1. identify the files or resources the task will touch
2. check for an existing active lock on those resources
3. either reserve the resource or wait/ escalate
4. record the reason for the reservation
5. release the lock when the task is complete or blocked and no longer needed

## Lock rules

- no task may edit a file without a corresponding lock
- the same resource cannot be locked by multiple active tasks
- a task may only release its own active lock
- if a task is blocked or abandoned, the lock must be released or explicitly transferred
- a conflict on a lock requires orchestrator review and a decision record

## Coordination policy

When two tasks overlap:

1. check the resource map
2. determine if the overlap is material
3. serialize the tasks or split scope
4. record a decision in `.agent/DECISIONS.md`
5. update the task board with the conflict status

## Resource reservation examples

```text
resource: src/auth/login.ts
resource_type: file
owner: implementation-agent
status: ACTIVE
reason: fix login flow bug
```

```text
resource: .github/workflows/
resource_type: directory
owner: release-manager
status: ACTIVE
reason: prepare release validation
```

## Escalation rules

If a task attempts to lock a resource already held by another task:
- the orchestrator must decide whether to queue, split, or deny
- the decision must be written to the decision ledger
- the blocked task remains in `BLOCKED` until the conflict is resolved

## Final rule

No editing decision is valid if it can overwrite an active lock without explicit coordination.
