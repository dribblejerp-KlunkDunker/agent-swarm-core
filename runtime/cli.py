"""Command-line front end for the swarm runtime.

Every command prints JSON so agents can parse results. State lives in the SQLite file named
by --db, SWARM_STATE_DB, or .swarm/state.sqlite3 in the current directory.

Approvals are deliberately awkward for an agent: `approval approve` needs an interactive
terminal where a person retypes the task ID. Outside production, --recorded-consent lets an
agent record approval that a named person gave in chat, quoting their words into the audit log.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .evidence import EvidenceBundle
from .repo_grounding import RepoGroundingEngine
from .services import RuntimeServices
from .task_state import TaskRecord, TaskStatus, unblock_targets

DEFAULT_DB = os.path.join(".swarm", "state.sqlite3")


class CommandError(Exception):
    pass


def _emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _production() -> bool:
    return os.environ.get("SWARM_ENV", "").strip().lower() in {"prod", "production"}


def _services(args: argparse.Namespace) -> RuntimeServices:
    db_path = args.db or os.environ.get("SWARM_STATE_DB") or DEFAULT_DB
    approver_authorizer = evidence_authorizer = None
    module_name = os.environ.get("SWARM_AUTHORIZER_MODULE")
    if module_name:
        # A deployment supplies identity checks as module attributes; see PRODUCTION_HARDENING.md.
        module = importlib.import_module(module_name)
        approver_authorizer = getattr(module, "approver_authorizer", None)
        evidence_authorizer = getattr(module, "evidence_authorizer", None)
    return RuntimeServices(
        db_path=db_path,
        approver_authorizer=approver_authorizer,
        evidence_authorizer=evidence_authorizer,
    )


def _task(services: RuntimeServices, task_id: str) -> TaskRecord:
    task = services.load_task(task_id)
    if task is None:
        raise CommandError(f"Unknown task {task_id!r}")
    return task


def _task_view(services: RuntimeServices, task: TaskRecord) -> Dict[str, Any]:
    view = asdict(task)
    view["status"] = task.status.value
    if task.status == TaskStatus.BLOCKED:
        view["may_resume_to"] = [state.value for state in unblock_targets(task.blocked_from)]
    approval = services.approvals.get(task.task_id)
    view["approval"] = None if approval is None else {
        "action": approval.action, "scope": approval.scope, "status": approval.status.value,
        "approver": approval.approver, "requester": approval.requester, "expires_at": approval.expires_at,
    }
    view["evidence_records"] = [
        {"title": bundle.title, "status": bundle.status.value, "source": bundle.source}
        for bundle in services.evidence.get(task.task_id)
    ]
    return view


# ---- task -------------------------------------------------------------------------------

def cmd_task_create(args: argparse.Namespace) -> Any:
    services = _services(args)
    task = TaskRecord(
        task_id=args.task_id, owner=args.owner, objective=args.objective, scope=args.scope or [],
        required_skills=args.skill or [], repo=args.repo or "", branch=args.branch or "",
        risk_level=args.risk, approval_action=args.action,
    )
    services.create_task(task)
    return _task_view(services, task)


def cmd_task_show(args: argparse.Namespace) -> Any:
    services = _services(args)
    return _task_view(services, _task(services, args.task_id))


def cmd_task_list(args: argparse.Namespace) -> Any:
    services = _services(args)
    entries = services.tasks.load().values()
    return [
        {"task_id": e.task_id, "status": e.status, "owner": e.owner, "objective": e.objective}
        for e in entries if args.status is None or e.status == args.status
    ]


def cmd_task_move(args: argparse.Namespace) -> Any:
    services = _services(args)
    task = _task(services, args.task_id)
    services.transition_task(
        task, TaskStatus(args.state), approval_scope=args.approval_scope, justification=args.justification
    )
    return _task_view(services, task)


def cmd_task_block(args: argparse.Namespace) -> Any:
    services = _services(args)
    task = _task(services, args.task_id)
    services.add_blocker(task, args.reason)
    return _task_view(services, task)


def cmd_task_ref(args: argparse.Namespace) -> Any:
    services = _services(args)
    task = _task(services, args.task_id)
    added = services.add_evidence_reference(task, args.reference)
    return {"added": added, "evidence": task.evidence}


# ---- evidence ---------------------------------------------------------------------------

def cmd_evidence_add(args: argparse.Namespace) -> Any:
    services = _services(args)
    _task(services, args.task_id)
    if (args.content is None) == (args.file is None):
        raise CommandError("Pass exactly one of --content or --file")
    content = args.content if args.content is not None else Path(args.file).read_text(encoding="utf-8")
    services.evidence.add(EvidenceBundle(
        task_id=args.task_id, title=args.title, content=content, source=args.source, tags=args.tag or [],
    ))
    return {"added": args.title, "status": "PENDING"}


def cmd_evidence_review(args: argparse.Namespace) -> Any:
    services = _services(args)
    _task(services, args.task_id)
    if args.verdict == "verify":
        changed = services.evidence.mark_verified(args.task_id, args.title, verifier=args.verifier)
    else:
        changed = services.evidence.mark_rejected(args.task_id, args.title, verifier=args.verifier)
    return {"changed": changed, "records": _task_view(services, _task(services, args.task_id))["evidence_records"]}


# ---- locks ------------------------------------------------------------------------------

def cmd_lock_reserve(args: argparse.Namespace) -> Any:
    services = _services(args)
    lease: Optional[int] = None if args.no_lease else args.lease
    acquired = services.locks.reserve(args.resource, args.task, args.owner, args.reason, lease_seconds=lease)
    holder = services.locks.check(args.resource)
    return {"acquired": acquired, "holder": None if holder is None else asdict(holder)}


def cmd_lock_renew(args: argparse.Namespace) -> Any:
    services = _services(args)
    return {"renewed": services.locks.renew(args.resource, args.task, args.owner, lease_seconds=args.lease)}


def cmd_lock_release(args: argparse.Namespace) -> Any:
    services = _services(args)
    return {"released": services.locks.release(args.resource, args.task, args.owner)}


def cmd_lock_list(args: argparse.Namespace) -> Any:
    services = _services(args)
    return [asdict(lock) for lock in services.locks.list_lock_records()]


# ---- approvals --------------------------------------------------------------------------

def cmd_approval_request(args: argparse.Namespace) -> Any:
    services = _services(args)
    task = _task(services, args.task_id)
    record = services.request_approval(task, scope=args.scope, approver=args.approver, notes=args.notes or "")
    return {"requested": record.action, "scope": record.scope, "approver": record.approver,
            "requester": record.requester, "expires_at": record.expires_at, "evidence": record.evidence}


def _confirm_interactively(task_id: str) -> None:
    if not sys.stdin.isatty():
        raise CommandError(
            "Approval needs a person at an interactive terminal. An agent must ask its user instead; "
            "outside production it may then pass --recorded-consent with the user's words."
        )
    typed = input(f"Type the task ID ({task_id}) to approve it: ").strip()
    if typed != task_id:
        raise CommandError("Confirmation did not match; nothing was approved")


def cmd_approval_approve(args: argparse.Namespace) -> Any:
    services = _services(args)
    task = _task(services, args.task_id)
    if args.recorded_consent:
        if _production():
            raise CommandError("--recorded-consent is not accepted in production")
        services.store.append_event(
            "approval.consent_recorded", task_id=task.task_id, actor=args.approver,
            payload={"consent": args.recorded_consent},
        )
    else:
        _confirm_interactively(task.task_id)
    approved = services.approvals.approve(task.task_id, approver=args.approver, evidence=list(task.evidence))
    record = services.approvals.get(task.task_id)
    return {"approved": approved, "status": None if record is None else record.status.value}


def cmd_approval_reject(args: argparse.Namespace) -> Any:
    services = _services(args)
    return {"rejected": services.approvals.reject(args.task_id, notes=args.notes, approver=args.approver)}


def cmd_approval_check(args: argparse.Namespace) -> Any:
    services = _services(args)
    task = _task(services, args.task_id)
    action = args.action or task.approval_action
    allowed = services.can_perform_action(task.task_id, action, scope=args.scope, evidence=list(task.evidence))
    denial = None
    if not allowed:
        with services.store.read_connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM audit_events WHERE task_id=? AND event_type='action.denied' "
                "ORDER BY sequence DESC LIMIT 1",
                (task.task_id,),
            ).fetchone()
        denial = json.loads(row["payload_json"]).get("reason") if row else None
    return {"allowed": allowed, "action": action, "scope": args.scope, "denial_reason": denial}


# ---- audit, health, grounding -----------------------------------------------------------

def _latest_checkpoint(path: str) -> Dict[str, Any]:
    """Read a checkpoint file: one JSON object, or the JSONL that `audit checkpoint --out` appends."""
    text = Path(path).read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise CommandError(f"Checkpoint file {path} is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise CommandError(f"Checkpoint file {path} is not valid JSON or JSONL") from exc


def cmd_audit_verify(args: argparse.Namespace) -> Any:
    services = _services(args)
    anchor = _latest_checkpoint(args.anchor) if args.anchor else None
    return services.store.verify_audit_chain(anchor=anchor)


def cmd_audit_checkpoint(args: argparse.Namespace) -> Any:
    services = _services(args)
    checkpoint = services.store.audit_checkpoint()
    if args.out:
        # Keep checkpoints outside the database directory, ideally on separately controlled storage.
        with open(args.out, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint, sort_keys=True) + "\n")
    return checkpoint


def cmd_audit_events(args: argparse.Namespace) -> Any:
    services = _services(args)
    events = services.store.list_events(after_sequence=args.after, limit=args.limit)
    return [e for e in events if args.task is None or e["task_id"] == args.task]


def cmd_health(args: argparse.Namespace) -> Any:
    health = _services(args).health_check()
    return asdict(health)


def cmd_ground(args: argparse.Namespace) -> Any:
    return RepoGroundingEngine(args.path).to_dict()


def cmd_selftest(args: argparse.Namespace) -> Any:
    from .validation import run_full_validation

    results = run_full_validation()
    return {
        "passed": all(result.passed for result in results),
        "checks": [{"name": r.name, "passed": r.passed, "details": r.details} for r in results],
    }


# ---- parser -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarm", description="Governed task runtime for agent swarms.")
    parser.add_argument("--db", help=f"state database (default: $SWARM_STATE_DB or {DEFAULT_DB})")
    commands = parser.add_subparsers(dest="command", required=True)
    states = [state.value for state in TaskStatus]

    selftest = commands.add_parser("selftest", help="run the runtime's own validation suite")
    selftest.set_defaults(func=cmd_selftest)
    ground = commands.add_parser("ground", help="inspect a repository and report facts, commands and risks")
    ground.add_argument("path", nargs="?", default=".")
    ground.set_defaults(func=cmd_ground)
    health = commands.add_parser("health", help="check database integrity, audit chain and configuration")
    health.set_defaults(func=cmd_health)

    task = commands.add_parser("task", help="create and move tasks").add_subparsers(dest="sub", required=True)
    create = task.add_parser("create")
    create.add_argument("task_id")
    create.add_argument("--owner", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--scope", action="append", help="path or area in scope (repeatable)")
    create.add_argument("--skill", action="append", help="required skill (repeatable)")
    create.add_argument("--repo")
    create.add_argument("--branch")
    create.add_argument("--risk", default="LOW", choices=["LOW", "MEDIUM", "HIGH"])
    create.add_argument("--action", default="release", help="irreversible action this task ends in")
    create.set_defaults(func=cmd_task_create)
    show = task.add_parser("show")
    show.add_argument("task_id")
    show.set_defaults(func=cmd_task_show)
    listing = task.add_parser("list")
    listing.add_argument("--status", choices=states)
    listing.set_defaults(func=cmd_task_list)
    move = task.add_parser("move")
    move.add_argument("task_id")
    move.add_argument("state", choices=states)
    move.add_argument("--justification", help="required when leaving BLOCKED")
    move.add_argument("--approval-scope", help="required for AWAITING_APPROVAL and RELEASED")
    move.set_defaults(func=cmd_task_move)
    block = task.add_parser("block")
    block.add_argument("task_id")
    block.add_argument("reason")
    block.set_defaults(func=cmd_task_block)
    ref = task.add_parser("ref", help="attach an evidence reference (an evidence title) to the task")
    ref.add_argument("task_id")
    ref.add_argument("reference")
    ref.set_defaults(func=cmd_task_ref)

    evidence = commands.add_parser("evidence", help="record and review evidence").add_subparsers(dest="sub", required=True)
    add = evidence.add_parser("add")
    add.add_argument("task_id")
    add.add_argument("--title", required=True)
    add.add_argument("--content")
    add.add_argument("--file", help="read evidence content from a file (e.g. a test log)")
    add.add_argument("--source", default="agent")
    add.add_argument("--tag", action="append")
    add.set_defaults(func=cmd_evidence_add)
    for verdict in ("verify", "reject"):
        review = evidence.add_parser(verdict)
        review.add_argument("task_id")
        review.add_argument("--title", help="one record; omit to review every eligible record")
        review.add_argument("--verifier", required=True)
        review.set_defaults(func=cmd_evidence_review, verdict=verdict)

    lock = commands.add_parser("lock", help="coordinate edits to shared resources").add_subparsers(dest="sub", required=True)
    reserve = lock.add_parser("reserve")
    reserve.add_argument("resource")
    reserve.add_argument("--task", required=True)
    reserve.add_argument("--owner", required=True)
    reserve.add_argument("--reason", required=True)
    reserve.add_argument("--lease", type=int, default=1800, help="seconds (default 1800)")
    reserve.add_argument("--no-lease", action="store_true", help="never expire (refused in production)")
    reserve.set_defaults(func=cmd_lock_reserve)
    renew = lock.add_parser("renew")
    renew.add_argument("resource")
    renew.add_argument("--task", required=True)
    renew.add_argument("--owner", required=True)
    renew.add_argument("--lease", type=int, default=1800)
    renew.set_defaults(func=cmd_lock_renew)
    release = lock.add_parser("release")
    release.add_argument("resource")
    release.add_argument("--task", required=True)
    release.add_argument("--owner", required=True)
    release.set_defaults(func=cmd_lock_release)
    lock_list = lock.add_parser("list")
    lock_list.set_defaults(func=cmd_lock_list)

    approval = commands.add_parser("approval", help="request and grant approval for irreversible actions")
    approvals = approval.add_subparsers(dest="sub", required=True)
    request = approvals.add_parser("request")
    request.add_argument("task_id")
    request.add_argument("--scope", required=True, help="exact target, e.g. production or main")
    request.add_argument("--approver", required=True, help="who must approve; cannot be the task owner")
    request.add_argument("--notes")
    request.set_defaults(func=cmd_approval_request)
    approve = approvals.add_parser("approve")
    approve.add_argument("task_id")
    approve.add_argument("--approver", required=True)
    approve.add_argument("--recorded-consent", help="dev only: the approver's own words, given in chat")
    approve.set_defaults(func=cmd_approval_approve)
    reject = approvals.add_parser("reject")
    reject.add_argument("task_id")
    reject.add_argument("--approver", required=True)
    reject.add_argument("--notes", default="")
    reject.set_defaults(func=cmd_approval_reject)
    check = approvals.add_parser("check", help="ask whether the irreversible action may proceed now")
    check.add_argument("task_id")
    check.add_argument("--scope", required=True)
    check.add_argument("--action", help="defaults to the task's approval action")
    check.set_defaults(func=cmd_approval_check)

    audit = commands.add_parser("audit", help="inspect and anchor the audit log").add_subparsers(dest="sub", required=True)
    verify = audit.add_parser("verify")
    verify.add_argument("--anchor", help="JSON file holding a checkpoint to verify against")
    verify.set_defaults(func=cmd_audit_verify)
    checkpoint = audit.add_parser("checkpoint")
    checkpoint.add_argument("--out", help="append the checkpoint to this JSONL file")
    checkpoint.set_defaults(func=cmd_audit_checkpoint)
    events = audit.add_parser("events")
    events.add_argument("--task")
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--limit", type=int, default=1000)
    events.set_defaults(func=cmd_audit_events)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except (CommandError, ValueError, RuntimeError, OSError) as exc:
        _emit({"error": str(exc), "command": args.command})
        return 2
    _emit(result)
    if args.command == "selftest" and not result["passed"]:
        return 1
    if args.command == "health" and not result["ready"]:
        return 1
    if args.command == "audit" and args.sub == "verify" and not result["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
