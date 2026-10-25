# Swarm Runtime

## Purpose

The swarm runtime is the control plane that turns specialist skills into a governed execution system.

The runtime is responsible for:

- creating and tracking tasks
- routing work to the right specialist skill chain
- enforcing state progression
- preventing conflicting edits
- capturing evidence
- enforcing approval for irreversible actions
- escalating when facts or authority are missing

## Runtime model

The runtime sits between the role layer and the repository / tool adapter layer.

### Layers

1. Role layer
   - project-grounding
   - task-planner
   - implementation-agent
   - evidence-auditor
   - security-reviewer
   - incident-responder
   - release-manager
   - swarm-orchestrator

2. Control layer
   - task registry
   - task state machine
   - lock manager
   - handoff tracker
   - evidence registry
   - decision ledger
   - approval gate

3. Runtime adapters
   - repository inspection
   - build and test runner
   - CI workflow integration
   - security review adapters
   - approval and notification bridges

## Task lifecycle

```text
INTAKE
  -> GROUNDED
  -> PLANNED
  -> READY
  -> IN_PROGRESS
  -> VERIFYING
  -> READY_FOR_RELEASE
  -> AWAITING_APPROVAL
  -> RELEASED
  -> CLOSED

Optional terminal states:
  -> BLOCKED
  -> CANCELLED
```

## Required task record

Every task must include:

```text
task_id:
owner:
primary_skill:
complementary_skills:
repo:
branch:
objective:
scope:
in_scope:
out_of_scope:
acceptance_criteria:
evidence_required:
status:
blockers:
created_at:
updated_at:
```

## Execution flow

1. Intake
   - normalize request
   - create task record
   - assign owner and initial status

2. Grounding
   - identify repo facts
   - determine relevant files
   - identify commands and constraints
   - record unknowns explicitly

3. Planning
   - create bounded plan
   - define acceptance criteria
   - determine required specialists
   - reserve resources and file locks

4. Implementation
   - perform only approved scope
   - record checkpoint before and after work
   - keep edits narrow and reversible

5. Verification
   - validate against objective evidence
   - record command output and outcome
   - decide if task passes, fails, or is blocked

6. Risk review
   - activate security-reviewer when required
   - escalate to human review for unsafe or unknown conditions

7. Release gate
   - require approval for irreversible action
   - verify release readiness
   - record final evidence and approval

8. Close
   - task enters CLOSED only after evidence and policy gates are satisfied

## Lock and conflict model

The runtime must prevent overlapping edits.

Before implementation, the task must reserve relevant files or resources.

If two tasks overlap:

- identify the conflict
- serialize the work or split scope
- escalate if needed
- update the task board and decision ledger

No task may edit a resource without a valid lock and a real task record.

## Evidence model

The runtime treats evidence as mandatory.

Each task must contain an evidence bundle with:

- claim
- command or source of truth
- working directory or repo context
- observed result
- expected result
- pass/fail/blocked status
- timestamp
- captured by

No completion claim is valid without an evidence record.

## Approval gate

Approval is required for:

- publish
- release
- deploy
- migration
- secret rotation
- destructive action
- external system write

Approval records must include:

- task_id
- requested_action
- action_scope
- evidence reviewed
- approving authority
- timestamp
- approval result

## Escalation rules

The runtime must escalate when:

- the repo cannot be grounded sufficiently
- scope is too broad for safe implementation
- evidence is missing or contradictory
- an irreversible action lacks approval
- lock conflicts cannot be resolved
- a task enters a deadlock or loop

Escalation produces a human-readable decision record and blocks execution until resolved.

## Operational outputs

For every task, the runtime must produce:

- task record
- state transition log
- lock status
- evidence bundle
- blocker report
- handoff record when needed
- approval record if required
- final closeout summary

## Safety principles

- one owner per task
- no hidden scope expansion
- no completion without evidence
- no irreversible action without approval
- no overlapping writes without coordination
- no unsupported repo claims without evidence

## Pilot status

This file is a pilot runtime artifact generated as part of the swarm architecture validation process.

It provides a compact runtime definition consistent with the repo’s architecture and governance documents.
