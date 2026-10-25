# Swarm Architecture / Control Plane

This repository contains a practical architecture for a swarm-based runtime that turns specialist skills into a governed operating system.

## What this repo contains

This repo captures the architecture for:

- swarm state machine
- orchestration engine
- lock and coordination model
- repo adapter model
- approval model
- evaluation framework
- field hardening and operations

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

## Operating principles

- no work without a task record
- no completion without evidence
- no irreversible action without approval
- no overlapping edits without coordination
- no unsupported repo claim without fact evidence
- no state jump without review

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

## Recommended usage

Use the repo as a reference implementation for the control plane and runtime rules behind an agent swarm. It is designed to be practical, audit-friendly, and suitable for real-world use with tight operational boundaries.

## Current status

This repo is the architecture and governance foundation for an operational swarm system intended to be used in real engineering environments.
