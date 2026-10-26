# Swarm State Model

This file defines the first hard enforcement layer for the swarm: a canonical task state machine and record schema.

The goal is to replace prose-only coordination with explicit state, ownership, and evidence.

## Core rule

Every task must be represented by a task record in `.agent/TASK_BOARD.md` and must transition through a defined state machine. A task is not considered complete unless its state and evidence are both recorded.

## Task states

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

Blocked or invalid states:
  -> BLOCKED
  -> CANCELLED
```

## Meaning of each state

### INTAKE
Initial state after a request is received.

Required fields:
- task_id
- title
- request summary
- primary owner
- repository
- created_at

### GROUNDED
Repository facts and constraints have been checked. The request is tied to observed repo evidence.

Required fields:
- repo summary
- relevant files
- commands discovered
- unknowns
- risk level

### PLANNED
The task has been reduced to a bounded slice with out-of-scope boundaries and acceptance criteria.

Required fields:
- objective
- in_scope
- out_of_scope
- acceptance_criteria
- evidence_required
- risks

### READY
The task is ready for execution, and all required prerequisites are known.

Required fields:
- owner assigned
- required specialists selected
- reserved files / resources
- evidence path documented

### IN_PROGRESS
Implementation is active.

Required fields:
- current assignee
- started_at
- change log or checkpoint summary

### VERIFYING
Implementation has been completed; evidence collection is underway.

Required fields:
- verification commands
- observed results
- blocker status
- failing evidence if any

### READY_FOR_RELEASE
The task is implemented and verified, and it is ready for final release or approval gating.

Required fields:
- evidence bundle complete
- security review status
- release notes summary
- rollback guidance

### AWAITING_APPROVAL
Irreversible work requires explicit approval before action.

Required fields:
- approval_requested_by
- approval_target
- approval_reason
- approval_deadline

### RELEASED
The irreversible action has been approved and executed.

Required fields:
- approved_by
- time_of_action
- result summary
- post_release_verification

### CLOSED
The task is complete and archived.

Required fields:
- final evidence
- closure reason
- resolution summary

### BLOCKED
The task cannot proceed due to missing evidence, missing permissions, unresolved dependency, or conflict.

Required fields:
- blocker summary
- blocking dependency or missing fact
- next action

### CANCELLED
The task was intentionally abandoned.

Required fields:
- cancellation reason
- owner of cancellation
- archived status

## Mandatory transition rules

The swarm must reject invalid transitions.

Examples:
- `INTAKE -> RELEASED` is invalid
- `GROUNDED -> RELEASED` is invalid without planning and verification
- `VERIFYING -> READY_FOR_RELEASE` is invalid unless evidence checks are recorded
- `READY_FOR_RELEASE -> RELEASED` is invalid without explicit approval when approval is required
- leaving `BLOCKED` requires a justification, and a task may only resume to the stage it was blocked from or an earlier one (a task blocked from `GROUNDED` cannot resume at `IN_PROGRESS`); a task blocked at `VERIFYING` or later resumes no later than `IN_PROGRESS`
- unblocking clears the blocker list; the audit log keeps every blocker that was added

## Required task record schema

Every task must include:

```text
task_id:
project:
repository:
branch:
owner:
primary_skill:
complementary_skills:
status:
title:
request:
objective:
scope:
in_scope:
out_of_scope:
acceptance_criteria:
relevant_files:
evidence_required:
blockers:
risk_level:
base_revision:
created_at:
updated_at:
last_handoff:
approval_required:
approved_by:
final_evidence:
```

## Required handoff schema

```text
handoff_id:
task_id:
from_agent:
to_agent:
status:
summary:
files_changed:
proof:
blockers:
next_action:
created_at:
```

## Required evidence schema

```text
proof_id:
task_id:
claim:
revision:
command:
source_file_or_log:
observed_result:
expected_result:
status: PASS | FAIL | BLOCKED | UNKNOWN
captured_by:
captured_at:
```

## Required decision schema

```text
decision_id:
task_id:
question:
context:
options_considered:
chosen_option:
reason:
evidence:
approver:
created_at:
```

## Resource lock model

To prevent conflicting edits, each file or resource used by a task must be reserved by a lock.

```text
lock_id:
resource:
resource_type: file | directory | tool | environment | dependency
owner:
task_id:
status: ACTIVE | RELEASED | EXPIRED
reason:
acquired_at:
released_at:
```

Rules:
- no two active locks may reserve the same file for different tasks
- a lock may be released only by the owning task or by the orchestrator in a documented escalation
- any task that requires a lock must declare why it is needed
- a lock is not a substitute for a plan; it is only a conflict-prevention device

## Minimal state rules for the swarm

1. No task may move from `INTAKE` to implementation without `GROUNDED`.
2. No task may move from `GROUNDED` to implementation without `PLANNED`.
3. No task may claim success without `VERIFYING` evidence.
4. No irreversible action may proceed without `AWAITING_APPROVAL` and a recorded approver.
5. No task may remain in `IN_PROGRESS` without an active owner and a checkpoint summary.
6. No task may remain in `BLOCKED` without a concrete next action.
7. No handoff is valid without a receiver, summary, evidence, blockers, and exact next action.
8. No decision may be silently overwritten; each change must record a fresh decision entry.

## Decision gate for this repo

The swarm must adopt this state model as the default expectation for all work.

This file is the minimum enforcement layer for the next step.
