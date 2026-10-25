# Swarm Architecture and Roadmap

## Executive summary

The current repo is already strong at the role-definition layer: each skill describes a specialist with clear responsibilities and safety boundaries. The next logical step is to move from a skill catalog to a real swarm runtime.

This next layer is not a new set of skills. It is a control plane that coordinates the skills, enforces task state, tracks evidence, prevents conflicting edits, records decisions, and gates irreversible actions.

The final system has three layers:

1. Role layer
   - `project-grounding`
   - `task-planner`
   - `implementation-agent`
   - `evidence-auditor`
   - `security-reviewer`
   - `incident-responder`
   - `release-manager`
   - `swarm-orchestrator`

2. Control layer
   - task state machine
   - task board
   - handoff protocol
   - resource lock system
   - approval model
   - audit ledger
   - evidence bundle registry

3. Runtime adapters
   - repository inspection adapter
   - workflow/CI adapter
   - secret and dependency scan adapter
   - test runner adapter
   - approval and notification adapter
   - execution and rollback adapter

The goal is not to create more agent personalities. The goal is to create a reliable operating system for agent work.

---

## Architecture model

### 1. Request intake

A request enters as a natural-language task, issue, or feature request.

The intake layer normalizes:
- title
- objective
- constraints
- repo context
- known files or symptoms
- security sensitivity
- risk level
- urgency

This creates the first `task_id` and initial state: `INTAKE`.

### 2. Grounding stage

The `project-grounding` skill inspects the actual repository state.

It establishes:
- repo purpose
- main directories
- relevant files
- build/test commands
- framework/language constraints
- known risks
- unknowns

If grounding fails, the system stops and labels the missing fact as `UNKNOWN`.

### 3. Planning stage

The `task-planner` turns the grounded request into bounded work slices.

A valid plan includes:
- objective
- in scope
- out of scope
- acceptance criteria
- evidence required
- risk and rollback notes
- required complementary specialists

If the scope is too broad or cannot be validated, the task is narrowed or refused.

### 4. Execution stage

The `implementation-agent` performs only the approved work.

The implementation stage must:
- read before editing
- reserve file/resource locks
- preserve architecture conventions
- keep the patch narrow and reversible
- record what changed and why
- create a checkpoint

This stage is not allowed to silently expand scope.

### 5. Verification stage

The `evidence-auditor` checks the result against the acceptance criteria.

The auditor requires objective proof, not narrative confidence.

Examples of valid evidence:
- test output
- build output
- file diff
- reproduction log
- repository state check

A task cannot move to `READY_FOR_RELEASE` without evidence.

### 6. Risk review stage

The `security-reviewer` activates automatically when the task touches:
- auth or authorization
- secrets or credentials
- dependency changes
- file system writes
- OS shell execution
- external calls
- CI/CD or deployment paths
- data or permission boundaries

A material security issue blocks progression until remediated or explicitly escalated.

### 7. Incident stage

The `incident-responder` activates when there is:
- failing build
- regression
- outage
- stack trace
- active production issue
- user-visible breakage

This skill stabilizes first, diagnoses with evidence, and chooses the smallest root-cause fix.

### 8. Release stage

The `release-manager` is the final gate.

This stage requires:
- evidence bundle complete
- relevant security review complete if triggered
- final diff review
- release notes or summary
- explicit approval for the irreversible action
- rollback/containment guidance

No publish, merge, or deployment proceeds without this.

---

## Control-plane components

### A. Swarm state machine

Task states:

```text
INTAKE
  -> GROUNDED
  -> PLANNED
  -> READY
  -> IN_PROGRESS
  -> VERIFYING
  -> READY_FOR_RELEASE
  -> AWAITING_APPROVAL
  -> RELEASED
  -> CLOSED

Alternative paths:
  -> BLOCKED
  -> CANCELLED
```

Required behavior:
- every task has one owner
- every task has a task record
- every state transition is explicit
- no state skips required gates
- no completion claim without evidence
- blocked tasks record the exact blocker and next action

### B. Task board

The task board is the system of record for swarm work.

Each task record must include:
- task_id
- title
- owner
- primary skill
- complementary skills
- repository
- branch/base revision
- objective
- scope
- out of scope
- acceptance criteria
- evidence required
- risk rating
- blockers
- state
- created/updated timestamps

### C. Handoff model

Every handoff includes:
- task name
- from agent
- to agent
- summary
- proof/evidence
- blockers
- exact next action
- timestamp

This prevents lost context between specialists.

### D. Decision ledger

The decision ledger records:
- rationale
- alternatives considered
- chosen option
- evidence used
- approver
- result

This is essential for explainability and auditability.

### E. Checkpoint log

The checkpoint log records progress milestones.

It answers:
- what changed
- what evidence was captured
- what state is next
- what remains blocked

### F. Resource lock system

The system must prevent overlapping edits.

Required lock semantics:
- reserve file or resource before edit
- prevent conflicting writes to same file
- allow explicit release only by the owner or orchestrator
- keep lock ownership tied to task_id
- apply to files, directories, datasets, and environment scopes when relevant

### G. Evidence bundle registry

Each task should maintain an evidence bundle with:
- command run
- revision tested
- output or log snippet
- observed result
- expected result
- status
- captured_by
- timestamp

This allows the system to prove completion without ambiguity.

### H. Approval model

Approval is required for irreversible actions like:
- merge
- deploy
- publish
- destructive migration
- secret rotation or credential changes
- external system writes

Approval records must include:
- approver
- scope approved
- action requested
- reason
- evidence reviewed
- time of approval

### I. Orchestration engine

The orchestrator is the central scheduler and decision-maker.

It is responsible for:
- creating task records
- selecting initial skill chain
- activating complementary skills automatically
- validating state transitions
- detecting conflict or deadlock
- determining when to escalate or ask a human
- routing work to the correct specialist

---

## Roadmap to the next operational layer

## Phase 0 — Normalize and lock contracts

Goal: make the role layer internally consistent.

Deliverables:
- consistent skill metadata across all skill files
- canonical definitions for owner, state, evidence, and approval
- no conflicting terminology between skills
- canonical `STATE_MODEL.md` and state transitions

Success criteria:
- every skill uses the same lifecycle language
- state progression is explicit
- every task has a single owner
- the handoff format is standard

## Phase 1 — Shared-state infrastructure

Goal: add the durable record layer.

Deliverables:
- `.agent/TASK_BOARD.md`
- `.agent/DECISIONS.md`
- `.agent/CHECKPOINTS.md`
- `.agent/PROJECT_CONTEXT.md`
- `.agent/STATE_MODEL.md`
- optional machine-readable JSON or YAML state files

Success criteria:
- it is possible to reconstruct task progression from repo files
- each task has a record of status, owner, and evidence
- handoffs and key decisions are auditable

## Phase 2 — Grounding and repo intelligence

Goal: eliminate repo guesswork.

Deliverables:
- repo inspection adapter
- manifest and toolchain detection
- command discovery from real repo files
- relevant-file map
- risk area identification
- `UNKNOWN` handling for unsupported assumptions

Success criteria:
- repo facts come from actual files and commands
- no language/framework assumptions without evidence
- task planner receives grounded facts before work begins

## Phase 3 — Planning and dependency graph

Goal: keep work bounded and verifiable.

Deliverables:
- task normalization template
- slice planning format
- dependency graph for tasks
- file and resource reservation logic
- risk/reversibility classification

Success criteria:
- every task can be broken into small slices
- acceptance criteria are objective and testable
- risky work has rollback or containment guidance

## Phase 4 — Controlled implementation and file safety

Goal: prevent conflicting or careless edits.

Deliverables:
- file/resource lock model
- pre-edit checkpoint
- patch-size or scope checks
- conflicting edit detection
- implementation summary and rollback note

Success criteria:
- no overlapping edits without coordination
- every patch maps back to a task and a scope decision
- the patch is small and reviewable

## Phase 5 — Evidence and validation automation

Goal: make verification a required gate.

Deliverables:
- evidence bundle schema
- verification command registry
- regression and targeted test selection
- evidence comparison against acceptance criteria
- `BLOCKED` / `UNKNOWN` status rules

Success criteria:
- every task has evidence linked to acceptance criteria
- no completion claim is accepted without proof
- targeted verification beats vague confidence claims

## Phase 6 — Security and incident workflows

Goal: add safety at scale.

Deliverables:
- secret scanning adapter
- dependency vulnerability review
- auth and permission path audits
- incident severity model
- rollback and containment strategy

Success criteria:
- security review is automatic when triggered
- incident triage is structured and evidence-backed
- high-risk work cannot pass without review

## Phase 7 — Release and approval hardening

Goal: prevent irreversible mistakes.

Deliverables:
- approval workflow
- release readiness gates
- dry-run and rollback guidance
- CI status integration
- GO/NO-GO release decision

Success criteria:
- no release proceeds without explicit approval
- no publish or deploy occurs without evidence
- release notes and rollback are preserved with the task record

## Phase 8 — Orchestration engine and evaluation harness

Goal: turn the swarm into a real system rather than a set of documents.

Deliverables:
- orchestrator routing rules
- parallelism with conflict detection
- escalation path to human approval
- benchmark suite for success and failure cases
- metrics for completion quality and drift

Success criteria:
- same task pattern yields consistent routing
- blocked tasks are surfaced quickly
- quality metrics become measurable
- false completion claims are reduced

---

## Immediate next actions

These are the next logical steps to start implementing in order:

1. Finalize the canonical task state model
2. Add the live task board and decision ledger
3. Add checkpoint and evidence schemas
4. Add the file/resource lock protocol
5. Add approval metadata and required gate logic
6. Document the orchestrator routing matrix
7. Add repo inspection layer and command discovery
8. Implement evaluation harness and benchmark cases
9. Add CI and dependency security adapters
10. Gate release actions behind explicit approval

---

## Success definition for the next evolution

The swarm is considered operationally mature when it can do all of the following reliably:

- accept a request and create a task record
- ground the task in actual repository evidence before implementation
- plan and assign a bounded slice
- prevent overlapping edits
- produce checkpoints and handoffs
- verify completion with objective evidence
- activate security review when triggers are met
- stabilize and diagnose incidents with evidence
- block release actions without proof or approval
- record decisions and rationale in an audit trail

This is the real next step beyond skills. It is the move from a conceptual swarm to a managed swarm runtime.

---

## Recommendation

The next implementation should prioritize these files first:

1. `.agent/STATE_MODEL.md`
2. `.agent/TASK_BOARD.md`
3. `.agent/DECISIONS.md`
4. `.agent/CHECKPOINTS.md`
5. `.agent/PROJECT_CONTEXT.md`
6. `SWARM_ARCHITECTURE.md`
7. `skills/swarm-orchestrator/SKILL.md`

Once that layer is in place, the repo is ready for the runtime adapters and evaluation harness.
