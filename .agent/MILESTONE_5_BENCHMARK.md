# Milestone 5 Benchmark and Scoring Model

## Purpose

This milestone turns the runtime from a set of enforcement mechanisms into a measurable operational system.

The benchmark layer answers one question clearly: is the swarm actually reliable under realistic operating conditions?

## Benchmark categories

### 1. Repo grounding benchmark

Goal: verify the system can inspect a repo without guessing.

Tasks:
- repo with clear README and manifest
- repo with missing README
- repo with conflicting manifests
- repo with incomplete metadata

Expected behavior:
- grounded repo facts are produced from direct evidence
- `UNKNOWN` is used whenever the fact is absent
- no unsupported framework or command claim is treated as fact

### 2. Lock conflict benchmark

Goal: ensure coordination safety works.

Tasks:
- two tasks reserve the same resource
- same task reserves the same resource twice
- a task attempts to continue after lock is blocked

Expected behavior:
- second lock attempt is rejected or treated as conflict
- resource ownership remains explicit
- lock state is visible and auditable

### 3. Evidence benchmark

Goal: ensure completion claims require proof.

Tasks:
- pass state without evidence
- pass state with evidence
- blocked task with missing proof

Expected behavior:
- no completion without evidence
- blocked state is recorded when proof is missing
- evidence is attached to the task outcome

### 4. Approval gate benchmark

Goal: verify irreversible actions are blocked until evidence and approval are present.

Tasks:
- deploy without evidence
- publish with evidence but no approval
- release with evidence and approval
- destructive action with missing approval

Expected behavior:
- irreversible path is rejected without approval + evidence
- approval gate records action, approver, and scope
- only approved actions proceed

### 5. Resume and recovery benchmark

Goal: ensure task state survives interruption and handoff.

Tasks:
- save in blocked state
- resume after checkpoint
- preserve evidence and blockers across restart

Expected behavior:
- task records are recoverable
- no evidence is silently lost
- ownership and blockers remain intact

## Scoring model

A benchmark task is scored from 0 to 100, based on four categories:

- architecture score: 25
- safety score: 25
- evidence score: 25
- benchmark score: 25

Total score = sum of category scores divided by 4 for a final 0–100 score.

## Pass criteria

A milestone passes when:

- all required benchmark categories run successfully
- no unsafe action is allowed without evidence or approval
- all blocked states are explicit and recoverable
- scoring output identifies where the runtime failed and why

## Required outputs

Each benchmark run should produce:

- task id
- benchmark category
- evidence used
- pass/fail result
- risk classification
- final score
- failure reason if failed

## Exit criteria

Milestone 5 is complete only when the runtime can produce repeatable benchmark outputs and flag failed or unsafe task behavior before it reaches a release state.
