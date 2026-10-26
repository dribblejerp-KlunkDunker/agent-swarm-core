---
name: agent-swarm-core
description: >
  Run multi-step or multi-agent engineering work under the agent-swarm-core governance runtime:
  every task gets a durable record, file locks, verified evidence, and a human approval before
  any irreversible action (merge, deploy, publish, migration, delete, secret rotation). Use when
  the user asks to run work "through the swarm", "with governance", "with approvals/audit", when
  several agents will edit the same repository, or before an irreversible action that should be
  gated. Drives the `swarm` CLI and its SQLite state and audit log.
---

# agent-swarm-core runtime

The runtime enforces the rules; this skill tells you how to work with it. It refuses invalid
moves, so when a command returns an error, read it and fix the cause. Never work around it.

## Setup (once per session)

```bash
python -m pip install --quiet git+https://github.com/dribblejerp-KlunkDunker/agent-swarm-core
swarm selftest | python -c "import json,sys; d=json.load(sys.stdin); print('selftest passed:', d['passed'])"
```

If `pip` cannot reach GitHub but the repository is checked out, use `python -m pip install <path>`
or run `python -m runtime` from the checkout instead of `swarm`.

State lives in `.swarm/state.sqlite3` in the current directory (`--db` or `SWARM_STATE_DB`
override it). Add `.swarm/` to the target repository's `.gitignore`; never commit the database.
Every command prints JSON. A non-zero exit code means it refused or failed.

## Identities

- You are `agent:<role>`, for example `agent:impl`. Use a different identity per sub-agent.
- The user is `human:<name>`. Only a human approves irreversible actions.
- Whoever owns a task (`--owner`) can never approve it. Evidence should be verified by a
  different identity from the one that produced it (for example `agent:auditor` reviews the
  output of `agent:impl`), after you have actually read the evidence.

## Workflow

1. **Ground.** Run `swarm ground .` and read the output. It lists facts, test commands and risk
   areas. Treat anything it can't establish as UNKNOWN; don't guess.
2. **Create one task per bounded slice of work.**
   ```bash
   swarm task create <id> --owner agent:impl --objective "<one sentence>" \
     --scope <path> --action <merge|deploy|publish|release|...> --risk <LOW|MEDIUM|HIGH>
   ```
   `--action` is the irreversible step the task ends in. Use `merge` for a PR merge.
3. **Advance through the stages in order.** Run `swarm task move <id> GROUNDED`, then
   `PLANNED`, then `READY`. Skipping a stage is refused.
4. **Lock before editing.**
   `swarm lock reserve <path> --task <id> --owner agent:impl --reason "<why>"`.
   If `acquired` is false, another task holds it. Stop and coordinate; don't edit anyway. A
   lock lasts 30 minutes, so renew it with `swarm lock renew` during long work.
5. **Implement.** Run `swarm task move <id> IN_PROGRESS`, make the change, then
   `swarm task move <id> VERIFYING`.
6. **Record real evidence.** Run the project's actual tests, build and lint, save the output, and attach it:
   ```bash
   swarm evidence add <id> --title test-log --file /path/to/test-output.txt --source "<command run>"
   swarm task ref <id> test-log
   swarm evidence verify <id> --title test-log --verifier agent:auditor
   ```
   Only verify evidence you have read and that supports the claim. If tests failed, record that
   honestly and reject it: `swarm evidence reject <id> --title test-log --verifier agent:auditor`.
7. **Get ready for release.** Run `swarm task move <id> READY_FOR_RELEASE`. This is refused unless
   every referenced piece of evidence is verified.
8. **Request approval.**
   `swarm approval request <id> --scope <exact target, e.g. main> --approver human:<name>`,
   then `swarm task move <id> AWAITING_APPROVAL --approval-scope <same scope>`.
9. **Ask the user.** Stop and show them what will happen: the action, the scope, a summary of
   the diff, and the evidence. Then ask for an explicit yes.
   - The user can approve in their own terminal: `swarm approval approve <id> --approver human:<name>`.
     It asks them to retype the task ID.
   - If the user approves in chat, record their words. This works only outside production:
     `swarm approval approve <id> --approver human:<name> --recorded-consent "<their exact words>"`.
     Never use `--recorded-consent` without a real, explicit approval from the user in this
     conversation. Never invent or paraphrase consent.
10. **Check right before acting.** Run
    `swarm approval check <id> --scope <scope>`. Perform the action only if `allowed` is true,
    and do exactly the approved action, nothing combined with it.
11. **Close out.** Run `swarm task move <id> RELEASED --approval-scope <scope>`, release your
    locks, then `swarm audit checkpoint --out <file outside the database directory>`.

## When something goes wrong

- **Blocked:** run `swarm task block <id> "<concrete blocker and next action>"`. To resume, run
  `swarm task move <id> <state> --justification "<what changed>"`. The `may_resume_to` field in
  `swarm task show` lists the allowed states; a task never resumes past the stage it was blocked from.
- **`approval check` denied:** read `denial_reason`.
  - `approval_not_granted`: the approval is still pending.
  - `action_mismatch` or `scope_mismatch`: you asked for something other than what was approved.
  - `evidence_mismatch`: the evidence changed, so request approval again.
  - `approval_expired`: approvals last 15 minutes; request a new one.
  - `separation_of_duties_unverified` or `separation_of_duties_violated`: request it again with
    `swarm approval request`, naming an approver who is not the task owner.
- **Abandoning work:** run `swarm task move <id> CANCELLED` and release the locks.

## Inspecting state

```bash
swarm task list                # every task and its status
swarm task show <id>           # full record, approval state and evidence records
swarm lock list
swarm audit events --task <id> # the append-only history for one task
swarm audit verify             # integrity of the hash chain
swarm health
```

## Limits to tell the user about

- Locks coordinate cooperating agents only. They don't stop other processes from editing files.
- Development mode (the default) has no identity provider. Anyone can claim any `human:` name,
  so the approval step is only as strong as your honesty about the user's consent. Production
  mode (`SWARM_ENV=production`) needs an audit key and identity adapters; see
  `PRODUCTION_HARDENING.md` in the agent-swarm-core repository.
