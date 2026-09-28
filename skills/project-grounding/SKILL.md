---
name: project-grounding
description: >
  Investigates the actual repository before implementation. Records what exists,
  what commands are valid, and which files are relevant. Use to anchor work in
  observed repo facts and avoid hallucinated assumptions.
metadata:
  author: agent-swarm-core
  version: "1.0"
includes:
  - ../.agent/**
---

# Project Grounding

Ground every task in the repository before proposing a fix or feature.

## Mission

Establish a fact-based understanding of the project:
- purpose
- structure
- build/test commands
- relevant files
- current constraints
- likely risk areas

## Required questions

Answer these before moving on:
- What is this repository for?
- What are the key directories and important entry points?
- What is the real build/test workflow?
- What files are directly relevant to this task?
- What assumptions are false or unsupported?
- What is the risk profile of this change?

## Output format

```text
Project Summary:
<short description of the repo>
Key Files:
- <path> — <why it matters>
Commands:
- <command> — <purpose>
Constraints:
- <restriction, toolchain, or rule>
Known Risks:
- <risk 1>
- <risk 2>
Unknowns:
- <item needing clarification>
```

## Grounding rules

- Prefer direct repository evidence over general knowledge.
- When the repo does not support a claim, mark it as `UNKNOWN`.
- Do not assume framework, language, or architecture unless verified.
- If a file is critical, read it before making a recommendation.
- Do not recommend broad refactors without repo evidence.

## Stop conditions

Stop and ask for clarification if:
- the repo cannot be confidently identified
- the task scope is missing
- the requested change conflicts with existing repo architecture
- the likely fix requires guessing rather than reading the code

## Common anti-patterns

- “This is a Node app” without checking package manifests
- “This should use Redis” without repo evidence
- “This is definitely a bug in X” without a reproducible issue
- recommending architecture based on memory rather than repo reality
