# Copilot repository instructions

This repository defines a general-purpose, anti-hallucination agent swarm for any software project.

## Core operating rules

- Ground every task in the actual repository state before changing code.
- Prefer small, bounded tasks over broad changes.
- Do not claim success without evidence: tests, diffs, logs, or direct file verification.
- Keep each task assigned to one owner.
- Maintain explicit handoffs between agents.
- If something is unknown, label it `UNKNOWN` and stop.
- Avoid scope creep. Small, verifiable slices win.
- Treat security and safety as first-class requirements.

## Required workflow

1. `project-grounding`
2. `task-planner`
3. `implementation-agent`
4. `evidence-auditor`
5. `security-reviewer` when applicable
6. `release-manager` for final checks

## Swarm file protocol

Create and maintain:

- `.agent/PROJECT_CONTEXT.md` — repo facts, commands, architecture, and constraints
- `.agent/TASK_BOARD.md` — active tasks and ownership
- `.agent/HANDOFFS/*.md` — explicit transitions between agents
- `.agent/CHECKPOINTS.md` — state and progress markers
- `.agent/DECISIONS.md` — non-obvious decisions and rationale

## Hard stop rules

- No silent rewrites.
- No speculative fixes without reproduction.
- No unverified success claims.
- No broad framework or architecture changes without explicit approval.
- No seeding secrets, tokens, or credentials into code or docs.
- No publishing or deployment without release-manager gates.

## Response style

When working in this repo, prefer:

- concise structured output
- clear ownership and status
- evidence-backed findings
- actionable next steps

Avoid:

- vague descriptions
- over-optimistic “fixed” claims
- broad architectural speculation
- multi-agent confusion without handoffs
