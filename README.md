# Swarm Architecture / Control Plane

This repository contains a practical architecture for a swarm-based runtime that turns specialist skills into a governed operating system.

## What this repo contains

This repo captures the architecture and working runtime checks for:

- swarm state machine
- orchestration engine
- lock and coordination model
- repo grounding and evidence model
- approval gate for irreversible action
- evaluation framework
- field hardening and operational safety
- final validation and release gate checks

## Runtime implementation

The runtime package is implemented in `runtime/` and includes:

- `task_state.py` — explicit task lifecycle and valid transitions
- `locks.py` — lock registry for resource coordination
- `evidence.py` — evidence tracking and verification state
- `approval.py` — approval and release gate enforcement
- `orchestrator.py` — skill-route selection
- `repo_grounding.py` — grounded repo inspection and unknown handling
- `task_board.py` — durable task board records
- `benchmark.py` — benchmark scoring and consistency checks
- `validation.py` — final validation suite for safety and release gates

## Core architecture documents

- `SWARM_ARCHITECTURE.md` — overall system and roadmap
- `SWARM_RUNTIME.md` — runtime control model
- `.agent/APPROVAL_MODEL.md` — approval model for irreversible actions
- `.agent/LOCK_MODEL.md` — lock and coordination rules
- `.agent/REPO_ADAPTER_MODEL.md` — repository grounding and evidence model
- `.agent/EVALUATION_FRAMEWORK.md` — benchmark and quality system
- `.agent/FIELD_HARDENING.md` — operational governance and field reliability
- `.agent/OPERATIONS_RUNBOOK.md` — practical usage and operations guide

## Why this exists

The swarm is not just a set of specialist agents or prompts. It is a system that requires:

- explicit state transitions
- evidence-backed execution
- safe coordination between tasks
- approval for irreversible action
- repository-grounded planning
- measurable quality and benchmark validation
- release-gate control before production actions

## Operating principles

- no work without a task record
- no completion without evidence
- no irreversible action without approval
- no overlapping edits without coordination
- no unsupported repo claim without fact evidence
- no state jump without review
- no release without evidence-backed gate approval

## Quick start

Read these in order:

1. `SWARM_ARCHITECTURE.md`
2. `SWARM_RUNTIME.md`
3. `.agent/REPO_ADAPTER_MODEL.md`
4. `.agent/LOCK_MODEL.md`
5. `.agent/APPROVAL_MODEL.md`
6. `.agent/EVALUATION_FRAMEWORK.md`
7. `.agent/FIELD_HARDENING.md`
8. `.agent/OPERATIONS_RUNBOOK.md`

## Runtime validation

The runtime includes a built-in validation module to check the final safety profile:

```bash
python - <<'PY'
from runtime.validation import run_full_validation
results = run_full_validation()
for result in results:
    print(result.name, result.passed, result.details)
PY
```

This exercises:

- invalid transition rejection
- lock conflict handling
- evidence-required completion gating
- approval-required irreversible-action blocking
- resume/recovery continuity
- benchmark consistency and scoring stability
- release gate finalization

## Recommended usage

Use the repo as a reference implementation for the control plane and runtime rules behind an agent swarm. It is designed to be practical, audit-friendly, and suitable for real-world use with tight coordination, evidence standards, and operational enforceability.

## Current status

This repo provides the architecture, runtime governance, and validation foundation for an operational swarm system intended for real engineering environments.
