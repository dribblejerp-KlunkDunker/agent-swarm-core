# Agent Swarm Core Roadmap

## Purpose

This roadmap evolves `agent-swarm-core` from a disciplined collection of skills into a dependable, evidence-driven super-team that can coordinate specialized agents across any software repository.

The target system is not simply “more agents.” It is a controlled operating system for agent work:

- every request is grounded in repository facts;
- every task has one accountable owner;
- complementary specialists are activated automatically;
- work is partitioned into bounded, verifiable slices;
- concurrent edits are safe and coordinated;
- security and operational risk are evaluated explicitly;
- no result is considered complete without evidence;
- publishing, deployment, and other irreversible actions require approval;
- decisions, handoffs, and evidence remain auditable after the session ends.

## Product vision

A user should be able to provide a request such as:

> “Add OAuth login, preserve the existing API, test it, and prepare it for release.”

The swarm should then be able to:

1. identify the repository and inspect its actual structure;
2. determine the relevant language, framework, commands, and constraints;
3. decompose the request into independently verifiable slices;
4. route each slice to the appropriate specialist;
5. identify complementary specialists automatically;
6. serialize conflicting edits while allowing safe parallel work;
7. maintain explicit ownership and handoffs;
8. implement only approved scope;
9. run targeted and regression verification;
10. perform security review because authentication is involved;
11. prepare release evidence and a clear GO/NO-GO decision;
12. stop and escalate whenever evidence, authority, or safety is insufficient.

## Guiding principles

1. **Evidence over confidence** — observed repository state, command output, diffs, logs, and tests outrank assumptions.
2. **One owner per task** — specialists may contribute evidence, but one agent owns the task state and next action.
3. **Smallest useful change** — prefer narrow, reversible patches over broad rewrites.
4. **Automatic complementarity** — activating a primary skill should automatically evaluate the skills needed to make its work safe and complete.
5. **Explicit uncertainty** — unsupported claims are labeled `UNKNOWN`; the swarm stops rather than guessing.
6. **Least privilege** — agents receive only the tools and scope required for their assigned slice.
7. **Parallelism with boundaries** — parallel work is encouraged only when file and dependency conflicts are controlled.
8. **No hidden state** — task status, decisions, checkpoints, and handoffs are written to shared swarm files.
9. **Human approval for irreversible actions** — merge, publish, deploy, destructive migration, credential changes, and external side effects require explicit approval.
10. **Operational usefulness** — every skill must produce a concrete artifact, decision, or verified action.

## Current baseline

The repository currently provides these core skills:

- `project-grounding`
- `task-planner`
- `implementation-agent`
- `evidence-auditor`
- `security-reviewer`
- `incident-responder`
- `release-manager`
- `swarm-orchestrator`

It also defines a protocol in `.agent/SWARM_PROTOCOL.md`, repository guidance in `.github/copilot-instructions.md`, and shared-state files such as the task board, handoffs, checkpoints, decisions, and project context.

The existing skills establish the behavioral contract. The roadmap below adds the operational machinery needed to make that contract repeatable, measurable, and automatable.

## Target operating model

### Request lifecycle

```text
request
  -> normalize
  -> identify repository and authority
  -> ground repository
  -> classify risk and task type
  -> build dependency-aware plan
  -> select primary owner
  -> activate complementary reviewers
  -> reserve files and resources
  -> implement bounded slice
  -> verify with objective evidence
  -> audit security and regression risk
  -> prepare release decision
  -> obtain approval for irreversible action
  -> publish outcome and archive evidence
```

### Standard agent roles

| Role | Direct responsibility | Primary output | When activated |
|---|---|---|---|
| Swarm orchestrator | Owns routing, sequencing, conflicts, and escalation | Execution plan and handoff state | Every multi-step or multi-skill task |
| Project grounding | Establishes verified repository facts | Grounding report | Before planning or implementation |
| Task planner | Converts goals into bounded slices | Plan with acceptance criteria | When work has more than one meaningful step |
| Implementation agent | Makes only the approved change | Patch summary and validation plan | For code, config, docs, or workflow changes |
| Evidence auditor | Determines whether claims are proven | PASS/FAIL/BLOCKED evidence report | After implementation and before release |
| Security reviewer | Finds security and permission risks | Risk rating and findings | Auth, secrets, input, dependencies, I/O, CI/CD, deployment, or data exposure |
| Incident responder | Stabilizes and diagnoses active failures | Incident report and minimal fix | Test failures, outages, regressions, broken builds, or urgent defects |
| Release manager | Performs final readiness and approval gate | GO/NO-GO release record | Before merge, publish, deployment, or other release action |

## Automatic complementary-skill rules

The orchestrator must not treat skills as isolated commands. Every primary skill should evaluate the following routing matrix before work begins.

| Trigger or task characteristic | Mandatory complementary skills | Reason |
|---|---|---|
| Any repository change | Project grounding, task planner, evidence auditor | Prevents guessing, uncontrolled scope, and unverified completion |
| Code or configuration change | Implementation agent, evidence auditor | Produces and proves the patch |
| Authentication, authorization, secrets, user input, external network, dependencies, file/system access, CI/CD, deployment | Security reviewer | Evaluates trust boundaries and unsafe behavior |
| Failing tests, broken build, regression, outage, stack trace, production defect | Incident responder, project grounding, evidence auditor | Stabilizes first and establishes a reproducible cause |
| Multiple files or specialists | Swarm orchestrator, task planner | Controls ownership, dependencies, and handoffs |
| Merge, tag, publish, deploy, migration, or external side effect | Release manager, evidence auditor, security reviewer when relevant | Prevents irreversible action without proof and approval |
| Documentation-only change | Project grounding, evidence auditor | Confirms documentation matches actual repository behavior |
| Dependency upgrade | Project grounding, security reviewer, evidence auditor, release manager | Validates compatibility, vulnerability exposure, and release readiness |
| Data/schema migration | Project grounding, task planner, security reviewer, evidence auditor, release manager | Requires rollback, data safety, compatibility, and explicit approval |

### Routing behavior

1. Select one **primary owner** based on the task's dominant need.
2. Add mandatory complementary skills from the matrix.
3. Add optional specialists only when evidence justifies them.
4. Create a task record before any edit.
5. Require each specialist to return its defined artifact.
6. Block downstream work if a required artifact is missing or marked `BLOCKED`.
7. Escalate to the user when authority, scope, or evidence is insufficient.

## Capability roadmap

### Phase 0 — Contract and inventory

**Objective:** Make the existing system internally consistent before adding automation.

**Deliverables:**

- inventory of every skill, shared file, output schema, and stop condition;
- consistent metadata across all `SKILL.md` files;
- documented ownership model;
- documented state-transition model;
- explicit distinction between advisory, blocking, and approval-required findings;
- compatibility policy for consuming repositories;
- initial roadmap and acceptance criteria.

**Acceptance criteria:**

- every skill declares inputs, outputs, owner behavior, blockers, and handoff target;
- every required shared file has a documented schema;
- no skill has conflicting terminology for status, evidence, or approval;
- orchestrator routing rules cover all current skills;
- unknown behavior is explicitly marked `UNKNOWN`.

**Risks:** inconsistent skill contracts, accidental behavior changes, ambiguous authority.

### Phase 1 — Shared state and audit ledger

**Objective:** Turn the `.agent/` directory into a durable coordination layer.

**Deliverables:**

- schema for `.agent/PROJECT_CONTEXT.md`;
- schema for `.agent/TASK_BOARD.md`;
- schema for `.agent/HANDOFFS/<task-id>.md`;
- schema for `.agent/CHECKPOINTS.md`;
- schema for `.agent/DECISIONS.md`;
- optional machine-readable counterparts such as `.agent/state/tasks.json` and `.agent/state/events.jsonl`;
- task IDs, timestamps, owner IDs, parent task IDs, and dependency references;
- append-only event rules for material decisions;
- archival policy for completed tasks.

**Required task states:**

```text
INTAKE
GROUNDED
PLANNED
READY
IN_PROGRESS
WAITING
BLOCKED
VERIFYING
SECURITY_REVIEW
READY_FOR_RELEASE
AWAITING_APPROVAL
RELEASED
CLOSED
CANCELLED
```

**Acceptance criteria:**

- every task can be reconstructed from its task record and event history;
- state transitions are explicit and invalid transitions are rejected;
- every handoff names the sender, receiver, evidence, blockers, and next action;
- decisions record alternatives considered and the reason for the chosen path;
- completed state is never inferred solely from chat text.

### Phase 2 — Grounding and repository intelligence

**Objective:** Replace repository guesswork with repeatable inspection.

**Deliverables:**

- repository identity and branch verification;
- file and directory inventory;
- language/framework/toolchain detection;
- manifest and lockfile detection;
- build, test, lint, format, type-check, and deployment command discovery;
- CI workflow discovery;
- entry-point and module map;
- ownership and CODEOWNERS inspection;
- sensitive-area detection for auth, secrets, payments, data, shell execution, network calls, and deployment;
- confidence levels for every inferred fact;
- a grounding report with evidence references.

**Implementation approach:**

1. Read repository metadata and branch state.
2. Inspect manifests, lockfiles, workflow files, and top-level documentation.
3. Identify commands from authoritative files before suggesting commands.
4. Search for task-relevant symbols, routes, configuration, tests, and integration points.
5. Record facts separately from interpretations.
6. Record unsupported assumptions as `UNKNOWN`.

**Acceptance criteria:**

- grounding never claims a language or framework without file evidence;
- discovered commands include their source file;
- relevant files are listed with a reason for relevance;
- risk areas are ranked and explain their evidence;
- the report can be consumed directly by the task planner.

### Phase 3 — Planning, dependency, and impact analysis

**Objective:** Make plans small enough to execute and prove.

**Deliverables:**

- task normalization template;
- slice planner with objective, scope, out-of-scope, acceptance criteria, evidence, risks, and rollback;
- dependency graph between slices;
- file/resource reservation list;
- impact estimator based on repository structure and symbol references;
- reversibility classification;
- definition-of-ready and definition-of-done gates;
- escalation rules for ambiguous or oversized requests.

**Slice categories:**

- discovery;
- reproduction;
- implementation;
- test/verification;
- security review;
- migration or rollout;
- documentation;
- release preparation.

**Planning rules:**

- one slice should have one owner and one primary outcome;
- mixed feature/refactor work is split unless explicitly approved;
- each slice must have at least one objective evidence source;
- high-risk slices must include rollback or containment;
- tasks with circular dependencies are blocked for human resolution;
- tasks affecting shared files are serialized or merged through an explicit integration owner.

**Acceptance criteria:**

- vague requests produce a bounded plan or a clarification request;
- dependency ordering is visible;
- expected file impact is compared with actual file impact;
- irreversible work cannot be marked ready without approval requirements.

### Phase 4 — Controlled implementation and change safety

**Objective:** Ensure implementation agents produce narrow, reviewable, reversible patches.

**Deliverables:**

- pre-edit checkpoint containing base commit and clean/dirty state;
- file reservation and conflict detection;
- implementation scope manifest;
- changed-file and changed-line budget where appropriate;
- pattern/convention inspection checklist;
- prohibited unrelated-edit detector;
- patch summary and risk notes;
- rollback instructions for every risky change;
- integration procedure for parallel work.

**Controls:**

- read relevant files before editing;
- require an approved task ID for edits;
- reject edits outside the approved scope unless the plan is amended;
- prevent two agents from editing the same file concurrently;
- preserve existing conventions unless a decision record authorizes change;
- capture the base revision before modification;
- never store credentials in the patch or swarm state.

**Acceptance criteria:**

- every changed file maps to a task scope item;
- the pre-edit revision is recorded;
- conflicts are detected before competing edits are applied;
- implementation output names validation commands;
- a rollback path exists for changes classified as risky or irreversible.

### Phase 5 — Evidence, testing, and regression assurance

**Objective:** Make “done” an evidence-backed state rather than a statement of confidence.

**Deliverables:**

- verification command registry;
- task-to-test mapping;
- targeted test runner selection;
- baseline/regression test policy;
- diff-to-acceptance-criteria comparison;
- evidence bundle format;
- evidence freshness rules;
- failure classification and blocker rules;
- reproducibility record for incidents and bug fixes.

**Evidence hierarchy:**

1. direct repository state;
2. deterministic reproduction;
3. focused test output;
4. broader regression test output;
5. build, lint, type-check, or static-analysis output;
6. diff inspection;
7. human review;
8. explanation or confidence language.

Lower-level evidence must not substitute for required higher-level proof when the task demands it.

**Acceptance criteria:**

- every acceptance criterion maps to evidence;
- command output includes command, working directory, timestamp, exit status, and relevant result;
- failed checks remain visible and block approval when material;
- evidence is tied to the task and revision tested;
- a passing unrelated test cannot be used as proof of the requested behavior.

### Phase 6 — Security and trust-boundary automation

**Objective:** Make security review systematic and proportionate to risk.

**Deliverables:**

- secret and credential scanning;
- unsafe shell and dynamic execution detection;
- input-validation and injection review checklist;
- authentication and authorization path mapping;
- permission and capability inventory;
- dependency and lockfile risk review;
- insecure logging and data-exposure checks;
- CI/CD and deployment command review;
- severity model and remediation SLA;
- false-positive suppression process with justification.

**Risk levels:**

- `LOW` — no meaningful trust-boundary change identified;
- `MEDIUM` — limited exposure or compatibility concern requiring review;
- `HIGH` — credible security impact or privilege/data boundary change;
- `CRITICAL` — active secret exposure, auth bypass, destructive capability, or severe exploitable path.

**Blocking findings:**

- secrets or tokens committed to the repository;
- auth or privilege bypass;
- unsanitized user-controlled command execution;
- destructive automation without safeguards;
- unreviewed dependency or deployment risk with material impact;
- inability to establish the affected trust boundary.

**Acceptance criteria:**

- security activation is automatic based on task classification;
- findings identify location, impact, evidence, and exact recommendation;
- severity and status are explicit;
- suppressions are recorded and approved;
- unresolved blocking findings prevent release.

### Phase 7 — Incident response and recovery operations

**Objective:** Give the swarm a safe path for active failures and regressions.

**Deliverables:**

- incident intake format;
- severity and blast-radius model;
- stabilization playbook;
- reproduction record;
- evidence-backed root-cause analysis;
- rollback and feature-flag decision path;
- minimal-fix workflow;
- post-incident review template;
- prevention and monitoring follow-up tasks.

**Incident sequence:**

```text
detect -> classify -> stabilize -> preserve evidence -> reproduce
  -> diagnose -> choose rollback or minimal fix -> verify
  -> monitor -> document -> create prevention work
```

**Acceptance criteria:**

- active incidents prioritize containment over feature work;
- hypotheses are labeled until proven;
- rollback is considered before speculative repair;
- blast radius and severity are documented;
- every resolved incident produces verification and prevention notes;
- incident changes pass evidence and security review when applicable.

### Phase 8 — Release, approval, and delivery gates

**Objective:** Prevent premature merge, publish, deployment, or other irreversible actions.

**Deliverables:**

- release readiness checklist;
- CI status and workflow evidence integration;
- final diff review;
- changelog/release-note generator;
- versioning policy;
- migration and rollback review;
- dry-run support;
- explicit approval record;
- GO/NO-GO decision artifact;
- post-release verification checklist.

**Release gates:**

1. scope and ownership are complete;
2. acceptance criteria are satisfied;
3. focused and required regression checks pass;
4. security review is complete when applicable;
5. unresolved blockers are zero or explicitly accepted by an authorized person;
6. final diff is reviewed;
7. release notes and rollback guidance exist;
8. the exact irreversible action has explicit approval;
9. post-release verification is defined.

**Acceptance criteria:**

- release manager can return `GO` or `NO-GO` with evidence for each gate;
- no release action occurs from implied approval;
- failed or stale CI evidence blocks release;
- deployment and migration dry-runs are separated from execution;
- post-release checks are assigned and recorded.

### Phase 9 — Orchestration engine and safe parallelism

**Objective:** Make the super-team behave as one coordinated system.

**Deliverables:**

- task classifier and routing rules;
- skill activation graph;
- dependency-aware scheduler;
- file/resource lock registry;
- handoff validator;
- circular-dependency detector;
- escalation manager;
- retry and resume behavior;
- checkpoint/recovery support;
- audit event stream;
- human approval interface.

**Scheduler rules:**

- grounding precedes planning;
- planning precedes implementation;
- implementation precedes final evidence;
- security review runs before release when risk triggers it;
- incident stabilization precedes diagnosis and repair;
- independent discovery and review tasks may run in parallel;
- conflicting edits are serialized;
- blocked dependencies pause downstream work;
- release manager is the final decision gate, not an implementation owner.

**Acceptance criteria:**

- the same request produces a predictable skill graph;
- no agent can silently bypass required gates;
- concurrent work cannot overwrite a reserved file;
- interrupted work resumes from a checkpoint without losing evidence;
- all routing and state transitions are auditable.

### Phase 10 — Metrics, evaluation, and continuous improvement

**Objective:** Measure whether the swarm is actually improving engineering outcomes.

**Metrics:**

- percentage of tasks grounded before editing;
- percentage of tasks with one owner;
- percentage with complete handoffs;
- percentage of completion claims backed by evidence;
- scope-drift rate;
- unrelated-file edit rate;
- conflict rate between parallel agents;
- rework rate;
- escaped defect rate;
- security findings by severity;
- mean time to stabilize incidents;
- mean time to verified resolution;
- release rollback rate;
- percentage of releases with complete approval evidence;
- false-positive rate of automated checks;
- user clarification rate;
- task completion time by task class.

**Evaluation suites:**

- ambiguous request benchmark;
- repository-without-tests benchmark;
- multi-file feature benchmark;
- security-sensitive change benchmark;
- dependency upgrade benchmark;
- failing-build incident benchmark;
- conflicting-parallel-edit benchmark;
- release-with-missing-evidence benchmark;
- prompt-injection and malicious-instruction benchmark.

**Acceptance criteria:**

- every major capability has positive and negative tests;
- unsafe requests are blocked reliably;
- valid requests are not unnecessarily blocked;
- evaluation results are versioned;
- skill changes include regression evaluation.

## Required support components

### Repository inspection adapter

Provides structured facts about branches, files, manifests, workflows, tests, dependencies, ownership, and repository state.

### Command and verification registry

Stores discovered commands with source, purpose, prerequisites, risk, expected output, and last-known result.

### Task state store

Stores task IDs, ownership, dependencies, status, scope, evidence, locks, approvals, and timestamps.

### File/resource lock manager

Prevents conflicting edits and records why a resource is reserved, by whom, and until when.

### Evidence bundle manager

Associates each claim with the exact revision, command, output, file, log, or reproduction used as proof.

### Security analysis adapter

Connects secret scanning, dependency analysis, static analysis, permission review, and trust-boundary inspection without treating any one tool as complete security proof.

### CI/CD adapter

Reads workflow status and logs, distinguishes stale from current results, and links checks to the tested revision.

### Approval manager

Records who approved what action, under which task and revision, with an expiration or scope boundary where appropriate.

### Notification and escalation adapter

Surfaces blockers, missing decisions, failed gates, approval requests, and incident severity changes.

## Shared artifact specifications

### Task record

```text
Task ID:
Parent Task:
Title:
Request:
Owner:
Status:
Primary Skill:
Complementary Skills:
Repository:
Base Revision:
Scope:
Out of Scope:
Dependencies:
Reserved Files/Resources:
Acceptance Criteria:
Evidence Required:
Risk Level:
Rollback Plan:
Blockers:
Next Action:
Created:
Updated:
```

### Handoff record

```text
Task:
From:
To:
Status at Handoff:
Summary:
Files Changed:
Evidence:
Known Risks:
Blockers:
Decision Needed:
Exact Next Action:
Revision:
Timestamp:
```

### Evidence record

```text
Task:
Claim:
Revision Tested:
Evidence Type:
Command or Source:
Working Directory:
Exit Status:
Observed Result:
Expected Result:
Status: PASS | FAIL | BLOCKED
Freshness:
Captured By:
Timestamp:
```

### Decision record

```text
Decision ID:
Task:
Question:
Context:
Options Considered:
Chosen Option:
Reason:
Evidence:
Risk:
Approver:
Status:
Date:
```

## Delivery sequence

The recommended implementation order is:

1. **Document and normalize contracts** — avoid automating inconsistent behavior.
2. **Strengthen shared state files** — create durable task, handoff, checkpoint, and decision records.
3. **Build repository grounding** — make facts and commands discoverable.
4. **Build planning and impact analysis** — control scope before edits.
5. **Add controlled implementation safeguards** — checkpoints, reservations, and scope checks.
6. **Build evidence and regression assurance** — make completion objectively verifiable.
7. **Add security automation** — attach risk-based review to the workflow.
8. **Harden incident response** — support containment, rollback, and root-cause work.
9. **Harden release management** — add CI evidence, approvals, dry-runs, and post-release checks.
10. **Implement orchestration and safe parallelism** — connect the skills into one scheduler.
11. **Add evaluation and metrics** — measure quality and prevent regressions.
12. **Optimize only after reliability is demonstrated** — speed must not weaken gates.

## Definition of done for the roadmap

The super-team is operationally mature when it can demonstrate all of the following in a test repository:

- accepts a natural-language request and produces a grounded task record;
- automatically selects a primary skill and all mandatory complementary skills;
- refuses to implement when the repository or scope is unknown;
- creates bounded slices with objective acceptance criteria;
- prevents overlapping edits to the same file;
- records checkpoints before changes;
- produces a patch whose files map to approved scope;
- runs the relevant verification commands;
- distinguishes pass, fail, blocked, and unknown evidence;
- activates security review for a security-sensitive change;
- activates incident response for a reproducible failure;
- blocks release when required evidence or approval is absent;
- produces complete handoffs and decision records;
- resumes safely after interruption;
- exposes enough audit history to reconstruct what happened;
- demonstrates measurable reductions in scope drift, unsupported claims, and escaped defects.

## Non-goals

This roadmap does not authorize:

- autonomous production deployment without human approval;
- unrestricted agent access to credentials or infrastructure;
- replacing human accountability with a score or confidence number;
- treating static analysis as complete security assurance;
- broad refactoring merely to improve architecture aesthetics;
- parallel edits without ownership and conflict controls;
- storing secrets, tokens, or sensitive production data in swarm artifacts;
- claiming a capability exists before it is implemented and verified.

## Immediate next steps

1. Add this roadmap to the repository.
2. Review the roadmap with the project owner and mark priorities.
3. Convert Phase 0 into bounded tasks on `.agent/TASK_BOARD.md`.
4. Define the canonical schemas for task, handoff, evidence, and decision records.
5. Add a routing matrix to the swarm protocol.
6. Create a minimal validation fixture repository for orchestration tests.
7. Implement the shared-state and evidence contracts before adding automation.
8. Run a first end-to-end demonstration using a small, non-production change.
9. Record every discovered mismatch as a decision or follow-up task.
10. Do not enable autonomous publishing or deployment until the release gates pass the evaluation suite.

## Priority labels

- **P0 — Safety-critical:** state integrity, grounding, ownership, evidence, security blockers, approval gates, rollback.
- **P1 — Core capability:** routing, dependency planning, locks, CI integration, incident workflow, release readiness.
- **P2 — Scale and quality:** parallel scheduling, adapters, metrics, evaluation harness, reporting.
- **P3 — Optimization:** performance, richer visualizations, predictive impact analysis, workflow convenience features.
