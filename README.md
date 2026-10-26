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
- `services.py` — single composition root that keeps every component on one state store
- `storage.py` — SQLite persistence, schema migrations and the keyed, anchorable audit chain
- `cli.py` — the `swarm` command-line interface (JSON output, for agents and people)

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

## Install and use

```bash
pip install git+https://github.com/dribblejerp-KlunkDunker/agent-swarm-core
swarm selftest                      # run the runtime's own audit
swarm ground .                      # repository facts, commands and risk areas
swarm task create fix-login --owner agent:impl --objective "Fix login redirect" --action merge
swarm task move fix-login GROUNDED
swarm lock reserve src/auth --task fix-login --owner agent:impl --reason "edit redirect"
swarm evidence add fix-login --title tests --file test-output.txt
swarm approval request fix-login --scope main --approver human:reviewer
swarm approval check fix-login --scope main
```

State lives in `.swarm/state.sqlite3` unless `--db` or `SWARM_STATE_DB` says otherwise. Every command prints JSON. `swarm approval approve` needs a person at an interactive terminal; see `.claude/skills/agent-swarm-core/SKILL.md` for the full agent workflow.

## Runtime validation

The runtime includes a built-in validation suite that checks the final safety profile:

```bash
python -m runtime selftest
```

This exercises:

- invalid transition rejection
- lock conflict handling
- evidence-required completion gating
- approval-required irreversible-action blocking
- resume/recovery continuity
- benchmark consistency and scoring stability
- release gate finalization
- durable state that survives reopening the database
- unblocking that cannot skip lifecycle stages
- compound actions and separation of duties for approvals
- a full production lifecycle on a real database with a keyed audit chain
- audit tamper detection: an unkeyed rewrite and a truncated history are both caught

## Recommended usage

Use the repo as a reference implementation for the control plane and runtime rules behind an agent swarm. It is designed to be practical, audit-friendly, and suitable for real-world use with tight coordination, evidence standards, and operational enforceability.

## Current status

This repo provides the architecture, runtime governance, and validation foundation for an operational swarm system intended for real engineering environments.
