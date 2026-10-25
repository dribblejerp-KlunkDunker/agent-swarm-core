# Swarm Protocol

This file defines the default coordination protocol for the agent swarm.

## Standard task lifecycle

### 1. Ground
The `project-grounding` skill must inspect the repository before implementation begins.

Required output:
- repo purpose
- key modules and directories
- build/test commands
- constraints or blockers
- likely relevant files

### 2. Plan
The `task-planner` skill converts the work into slices.

Each slice should include:
- objective
- scope
- out of scope
- acceptance criteria
- evidence required

### 3. Implement
The `implementation-agent` performs only the approved change.

Rules:
- read before editing
- do not mix unrelated edits
- keep patch scope tight
- preserve existing patterns unless instructed otherwise

### 4. Verify
The `evidence-auditor` checks the result.

Required proof:
- file changes or diff
- passing test output or verification command
- log excerpts or reproduction evidence

### 5. Review
The `security-reviewer` checks for risk if the task touches auth, secrets, dependencies, I/O, or deployment.

### 6. Release
The `release-manager` performs final readiness checks before any push or deployment.

## State model and enforcement

The swarm must operate on a canonical task state model defined in `.agent/STATE_MODEL.md`.

This is the minimum required contract:

- every task must have a task record
- every task must have a status
- every task must have one owner
- every task must have explicit evidence at verification time
- every irreversible action requires approval
- every handoff must use the handoff schema
- every file or resource used by a task must be reserved by a lock when conflict is possible

## State machine

```text
INTAKE -> GROUNDED -> PLANNED -> READY -> IN_PROGRESS -> VERIFYING -> READY_FOR_RELEASE -> AWAITING_APPROVAL -> RELEASED -> CLOSED
                               \                          \                         \
                                \-> BLOCKED -------------------> READY
```

The state machine is authoritative. Invalid transitions are rejected.

## Task ownership

Use this format:

```text
Task: <short name>
Owner: <agent or person>
Status: <planned / in-progress / blocked / done>
Evidence: <what proves current state>
Next: <exact next action>
```

## Handoff format

Every handoff must include:

```text
Task: <task name>
From: <agent>
To: <next agent>
Summary: <what changed>
Evidence: <proof>
Blockers: <none or exact blocker>
Next Action: <exact next step>
```

## Shared state files

Create and maintain:

- `.agent/PROJECT_CONTEXT.md` — repo facts, commands, architecture, and constraints
- `.agent/TASK_BOARD.md` — active tasks and ownership
- `.agent/HANDOFFS/*.md` — explicit transitions between agents
- `.agent/CHECKPOINTS.md` — state and progress markers
- `.agent/DECISIONS.md` — non-obvious decisions and rationale
- `.agent/STATE_MODEL.md` — authoritative task and evidence state model

## Safety rules

- No direct edits across unrelated subsystems.
- No assumptions without evidence.
- No “done” without verification.
- No deployment without approval.
- No secret storage in repo or chat logs.
- No task may advance to a later state without a documented state transition and supporting evidence.
- No conflicting file locks may be active for the same resource.
