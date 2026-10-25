# Milestone 1 Audit — Runtime Execution Core

## Purpose

This audit verifies whether the first execution milestone is consistent with the swarm architecture and safe enough to advance.

## Required audit passes

### 1. Architecture audit

Check:
- TaskRecord state model matches the repo lifecycle
- No invalid transitions are allowed
- Ownership and objective are explicit
- state machine stays inside the defined lifecycle boundaries

Pass condition:
- all state changes are valid and explicit

### 2. Safety audit

Check:
- lock registry prevents overlapping resource writes
- task ownership is tied to the lock owner
- invalid or conflicting locks are rejected
- unsafe state transitions are blocked

Pass condition:
- no overlapping edit can proceed without lock resolution

### 3. Evidence audit

Check:
- evidence is attached to task claims
- pass states require evidence
- blocked or unknown states are recorded properly
- no “done” state is accepted without proof

Pass condition:
- evidence is required and directly tied to claims

### 4. Benchmark audit

Run the benchmark harness against a simple task flow.

Checklist:
- INTAKE -> GROUNDED -> PLANNED -> READY -> IN_PROGRESS -> VERIFYING -> CLOSED
- a conflicting lock is rejected
- evidence is required before pass state
- blocked tasks record blockers explicitly

Pass condition:
- benchmark result is stable and no unsafe transition is accepted

## Exit criteria for milestone 1

Milestone 1 is complete only when:

- task state validation passes
- resource locks work
- evidence is recorded and required
- orchestrator routing is deterministic for simple task types
- benchmark harness returns predictable results

## If this milestone fails

If any audit fails, the milestone does not advance to Milestone 2.

The failure must be recorded with:
- failing check
- offending file or function
- required fix
- follow-up benchmark
