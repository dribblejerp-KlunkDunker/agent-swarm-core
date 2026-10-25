# Milestone 2 Implementation

## Goal

Milestone 2 adds the first concrete repo-grounding layer to the swarm runtime. It converts repo inspection from a conceptual rule into a live fact extractor.

## What is implemented

- `runtime/repo_grounding.py`
  - inspects the repository root
  - detects manifests and likely project type
  - infers key files and directories
  - identifies common commands
  - surfaces risk areas and unknowns
  - emits a JSON-friendly grounding report

## Why this matters

This is the first operational step away from architecture-only reasoning and toward evidence-backed task planning.

## Audit expectations

Milestone 2 must pass:

- architecture audit: repo facts are grounded in repo evidence
- safety audit: no assumptions without evidence
- evidence audit: unknowns are explicit and tied to missing data
- benchmark audit: ambiguous repo states do not get guessed

## Next milestone

After this milestone passes the audit gate, the next step is durable task records and recovery logic.
