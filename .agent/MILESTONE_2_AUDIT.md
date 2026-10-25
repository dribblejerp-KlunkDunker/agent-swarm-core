# Milestone 2 Audit Template — Repo Grounding Automation

## Purpose

This audit ensures the repo grounding layer behaves like a true evidence extractor instead of an assumption engine.

## Required checks

### Architecture audit
- grounding output is derived from repository facts
- unknown assumptions are explicitly labeled `UNKNOWN`
- repo facts are separated from interpretation

### Safety audit
- no framework or command inference without direct evidence
- risky areas are surfaced before implementation begins
- ambiguous repo state leads to BLOCKED or REQUIRES_REVIEW

### Evidence audit
- every fact has a source or file reference
- evidence is required for task planning and implementation
- no command is proposed without repo-backed validation

### Benchmark audit
- run a repo with incomplete or contradictory signals
- ensure system refuses to guess and refuses unsafe execution

## Exit criteria

Milestone 2 is complete only when repo grounding is automated and strictly evidence-based.
