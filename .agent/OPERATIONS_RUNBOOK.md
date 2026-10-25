# Swarm Operations Runbook

This runbook defines how to operate the swarm architecture in the field.

## 1. Mission

Use the swarm to complete bounded technical work safely, predictably, and audibly while keeping every task state, evidence bundle, approval record, and lock in place.

## 2. Operating principles

- no work without a task record
- no completion without evidence
- no irreversible action without approval
- no hidden scope expansion
- no overlapping file edits without coordination
- no state jump without validation
- no unresolved blocker without explicit status
- no unsupported repo claim without fact evidence

## 3. Standard task flow

A task proceeds through these stages:

1. intake
2. repo grounding
3. planning
4. ready
5. implementation
6. verification
7. risk review if triggered
8. release gate if required
9. approval if required
10. closure

If a task cannot satisfy a required phase, it must be marked BLOCKED or REQUIRES_REVIEW.

## 4. Required task record

Each task must contain:

- task_id
- title
- owner
- repository and branch
- objective
- scope
- out-of-scope
- acceptance criteria
- required skills
- risk level
- evidence requirements
- blockers
- current status
- last updated timestamp

## 5. Required repo grounding

Before work starts, confirm:

- repo purpose
- language and framework
- relevant directories and files
- known build/test commands
- relevant constraints
- known risks
- unknowns

Do not proceed on assumptions.

## 6. Planning gates

Before implementation:

- define the objective
- confirm acceptance criteria
- define required evidence
- identify required skills
- identify resource locks
- identify risk and rollback profile

If the task is vague, broad, or under-specified, narrow it or block it.

## 7. Lock behavior

Before editing:

- identify affected files/resources
- check for active locks
- acquire the relevant lock
- record reason and ownership
- release only when work is complete, blocked, or transferred

If a lock conflict occurs, the task must be serialized, split, or escalated.

## 8. Evidence requirements

Every task must produce evidence tied to acceptance criteria.

Examples:

- test output
- build output
- reproduction log
- diff inspection
- verification result
- security scan result

Evidence must be objective and reviewable.

## 9. Approval policy

Approval is required for:

- merges into protected states
- deployment or publish actions
- schema or data migration
- secrets or credential changes
- destructive cleanup
- any irreversible side effect

Approval must include:

- action
- scope
- evidence reviewed
- approver
- timestamp
- approval outcome

No irreversible action proceeds without a recorded approval.

## 10. Checkpointing

At key milestones, record:

- what changed
- what evidence exists
- what remains blocked
- what is next
- whether a lock or approval gate is active

This keeps work resumable and auditable.

## 11. Incident handling

If a task fails or the system becomes unstable:

1. stabilize first
2. document the failure
3. capture evidence
4. isolate root cause
5. avoid broad rewrite
6. validate the fix before closure

## 12. Escalation conditions

Escalate to a human when:

- repo facts are unclear
- scope is too broad
- evidence is missing
- approval is required but unavailable
- the task is deadlocked
- a policy conflict cannot be resolved internally
- security or production risk is too high

## 13. Closure conditions

A task can close only when:

- repo evidence is complete
- validation has passed
- acceptance criteria are met
- the evidence bundle is recorded
- final state is valid
- approvals are recorded where required

## 14. Daily operations checklist

Before work:

- confirm task status
- confirm owner
- confirm repo facts
- confirm resource locks
- confirm acceptance criteria

During work:

- record checkpoints
- keep patch scope tight
- log blockers early
- maintain evidence trail

Before close:

- validate acceptance criteria
- confirm evidence bundle
- confirm locks are released
- confirm approvals if needed
- document final status

## 15. Metrics to watch

Track:

- grounding rate
- evidence completeness
- blocked task rate
- approval compliance
- lock conflicts
- deadlock frequency
- incident resolution quality
- release safety compliance

## 16. Final rule

A swarm is safe not because it is confident. It is safe because it is constrained, evidence-driven, and policy-bound.

This runbook is the practical operating layer that makes the full swarm architecture usable in the field.
