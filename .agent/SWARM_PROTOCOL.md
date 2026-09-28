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

## Task ownership

Use this format:

```
Task: <short name>
Owner: <agent or person>
Status: <planned / in-progress / blocked / done>
Evidence: <what proves current state>
Next: <exact next action>
```

## Handoff format

Every handoff must include:

```
Task: <task name>
From: <agent>
To: <next agent>
Summary: <what changed>
Evidence: <proof>
Blockers: <none or exact blocker>
Next Action: <exact next step>
```

## Safety rules

- No direct edits across unrelated subsystems.
- No assumptions without evidence.
- No “done” without verification.
- No deployment without approval.
- No secret storage in repo or chat logs.
