# Agent Swarm Core

A practical, anti-hallucination skill stack for working on any repository or project without losing direction.

## The principle

The swarm is not a free-form chat. It is a disciplined operating model:

- One task has one owner.
- Every task is bounded.
- Every claim must be backed by evidence.
- Every handoff is explicit.
- No guessing, no scope creep, no silent rewrites.

## Core swarm rules

1. Ground before changing anything.
2. Plan small, testable slices.
3. One owner per task.
4. Evidence beats confidence.
5. If unknown, say `UNKNOWN` and stop.
6. If a task is ambiguous, ask for a decision or narrow it.
7. If a fix is risky, prepare rollback guidance.
8. Never treat repository docs as truth unless verified against the codebase.

## This repo contains

- `skills/swarm-orchestrator` — routes tasks and keeps the swarm coherent
- `skills/project-grounding` — inspects the real repo and records facts
- `skills/task-planner` — breaks work into bounded slices
- `skills/evidence-auditor` — verifies all outputs with proof
- `skills/implementation-agent` — does the actual work in a controlled way
- `skills/security-reviewer` — checks for risk and unsafe changes
- `skills/release-manager` — final readiness and publishing gate
- `skills/incident-responder` — stabilizes breakages and root causes

## Minimal swarm workflow

```
project-grounding -> task-planner -> implementation-agent -> evidence-auditor -> security-reviewer -> release-manager
```

For an incident:

```
incident-responder -> project-grounding -> implementation-agent -> evidence-auditor -> release-manager
```

## Shared swarm files

Use these files in every project:

- `.agent/PROJECT_CONTEXT.md`
- `.agent/TASK_BOARD.md`
- `.agent/HANDOFFS/<task-id>.md`
- `.agent/CHECKPOINTS.md`
- `.agent/DECISIONS.md`

## Default refusal rule

If the request cannot be grounded in repo evidence, or if scope is too large to safely bound, the swarm does not proceed. It narrows, asks, or refuses the unsafe path.

## Best use

Use this stack when you need:

- reliable implementation without drifting goals
- better agent coordination
- less hallucination and more evidence
- reusable operating discipline across any repo

---

This is intentionally boring and strict by design. Boring is reliable.
