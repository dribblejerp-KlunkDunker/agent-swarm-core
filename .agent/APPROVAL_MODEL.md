# Approval Model

This file defines the approval gate for irreversible or high-risk work.

## Purpose

The swarm must not perform a destructive or externally visible action without a recorded approval. This includes releases, deploys, merges into controlled states, destructive migrations, secret rotations, and other operations with material side effects.

## Approval triggers

A task enters the approval path when it includes any of the following:

- publish or release
- deployment or environment mutation
- merge to a protected branch
- schema or data migration
- secret management action
- credential or token rotation
- broad destructive cleanup
- external-system writes or network side effects

## Approval requirements

Every approval must contain:

```text
approval_id:
requested_by:
task_id:
requested_action:
action_scope:
reason:
reviewed_evidence:
approver:
approval_status: APPROVED | REJECTED | DEFERRED
created_at:
expires_at:
```

## Approval rules

- approval is explicit, not implied
- approval applies to a specific action and scope
- approval must be recorded before execution
- if evidence changes after approval, re-approval is required
- if the task becomes blocked, approval is re-evaluated
- release-manager must confirm final readiness before approval is granted

## Approval states

```text
PENDING -> APPROVED
PENDING -> REJECTED
PENDING -> DEFERRED
APPROVED -> EXECUTED
APPROVED -> REVOKED
```

## Approval gate

A task may proceed to irreversible action only if:

1. the task is in `READY_FOR_RELEASE`
2. the evidence bundle is complete
3. relevant risk review is complete
4. final diff review is complete
5. approval record exists and is active
6. the action target matches the approved scope

## Escalation rules

If approval is refused or deferred:
- the task remains in `AWAITING_APPROVAL` or `BLOCKED`
- the exact reason must be recorded
- the next required decision must be documented
- no irreversible action is allowed to continue

## Mandatory output format

```text
Approval Request:
- task_id
- action
- scope
- why this is needed
Evidence Reviewed:
- <link or summary>
Risk Notes:
- <primary concern>
Approval Decision:
- APPROVED | REJECTED | DEFERRED
Approved By:
- <person or agent>
Timestamp:
- <time>
```

## Security requirement

Approval records must never include secrets, tokens, or raw credentials. They should reference actions and evidence, not credential values.

## Final rule

No irreversible action is valid without a fresh approval record and a matching evidence bundle.
