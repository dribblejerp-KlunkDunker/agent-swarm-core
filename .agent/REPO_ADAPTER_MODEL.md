# Repo Adapter Model

This file defines the repository intelligence layer used by the swarm runtime.

## Purpose

The repo adapter converts raw repository state into structured, trusted facts that the swarm can reason over. It is the bridge between the codebase and the orchestrator.

## Core responsibilities

The repo adapter must provide:

- repository identity and branch context
- file and directory inventory
- manifest and configuration detection
- language and framework identification
- build, test, lint, and deploy commands
- dependency inventory and lockfile analysis
- entry-point and module map
- risk area classification
- file relevance ranking for the active task
- evidence references tied to actual files and commands

## Inputs

The adapter reads from:

- repo root and branch metadata
- manifests and config files
- CI workflow files
- package managers and lockfiles
- source tree structure
- Git history and patch state when available

## Required outputs

The adapter must produce a structured grounding record:

```text
repo_summary:
primary_language:
frameworks:
key_directories:
entry_points:
commands:
relevant_files:
constraints:
known_risks:
unknowns:
confidence_level:
```

## Evidence rules

The repo adapter must distinguish between:

- observed fact
- inferred fact
- hypothesis
- unknown

It may only claim a fact when the repo supports it directly.

Examples:
- valid fact: `package.json` exists and has a script named `test`
- invalid fact: “this is a Node backend” without checking package files

## Required repository checks

The adapter should inspect, at minimum:

- manifest files
- package manager lockfiles
- test configuration
- CI workflow files
- docker and deployment files
- environment configuration files
- auth and secret-related paths
- dependency manifests
- top-level source directories

## Task relevance scoring

Given a task, the adapter should score relevant files by:

- direct symbol or keyword match
- module ownership
- architecture proximity
- likely risk area
- file path importance
- prior task relationship

## Output contract

The adapter returns a grounding artifact that the planner and implementation agent can consume.

```text
Project Summary:
<repo purpose>
Key Files:
- <path> — <why it matters>
Commands:
- <command> — <purpose>
Constraints:
- <restriction>
Known Risks:
- <risk>
Unknowns:
- <unknown>
```

## Safety constraints

- never fabricate framework or architecture details
- never assign a command without a source file or repo state
- never treat docs as a substitute for code evidence
- never assume production safety from local assumptions
- if a fact cannot be verified, record `UNKNOWN` and stop

## Integration contract

The repo adapter feeds directly into:

- `project-grounding`
- `task-planner`
- `implementation-agent`
- `evidence-auditor`
- `security-reviewer`

It is the factual substrate of the swarm.
