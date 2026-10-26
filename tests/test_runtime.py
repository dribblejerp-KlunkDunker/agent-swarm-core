from __future__ import annotations

import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import finalize_release_gate
from runtime.approval import ApprovalGate, ApprovalStatus, ReleaseGate
from runtime.benchmark import BenchmarkRunner
from runtime.evidence import EvidenceBundle, EvidenceRegistry, EvidenceStatus
from runtime.locks import LockRegistry
from runtime.repo_grounding import RepoGroundingEngine
from runtime.storage import SQLiteStateStore
from runtime.task_board import TaskBoard
from runtime.task_state import TaskRecord, TaskStateMachine, TaskStatus
from runtime.validation import run_full_validation


class ApprovalGateTests(unittest.TestCase):
    def test_evidence_does_not_auto_approve(self) -> None:
        gate = ApprovalGate()
        evidence = ["test log"]
        gate.request("task-1", "deploy", "production", "reviewer", evidence=evidence)
        self.assertFalse(gate.can_proceed("task-1", "deploy", evidence=evidence, scope="production"))
        self.assertEqual(gate.get("task-1").status, ApprovalStatus.PENDING)
        self.assertTrue(gate.approve("task-1", approver="reviewer", evidence=evidence))
        self.assertTrue(gate.can_proceed("task-1", "deployment", evidence=evidence, scope="production"))

    def test_approval_is_bound_to_action_scope_evidence_and_audit_proof(self) -> None:
        gate = ApprovalGate()
        evidence = ["test log", "diff"]
        gate.request("task-2", "deploy", "production", "reviewer", evidence=evidence)
        self.assertTrue(gate.approve("task-2", approver="reviewer", evidence=evidence))
        record = gate.get("task-2")
        self.assertTrue(record.approval_event_hash)
        self.assertFalse(gate.can_proceed("task-2", "publish", evidence=evidence, scope="production"))
        self.assertFalse(gate.can_proceed("task-2", "deploy", evidence=evidence, scope="staging"))
        self.assertFalse(gate.can_proceed("task-2", "deploy", evidence=["changed log"], scope="production"))
        self.assertEqual(gate.get("task-2").status, ApprovalStatus.BLOCKED)

    def test_tampered_approval_row_without_grant_proof_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "approval.sqlite3")
            gate = ApprovalGate(db_path=db_path)
            gate.request("task-tamper", "deploy", "production", "reviewer", evidence=["review"])
            with gate.store.transaction() as connection:
                row = connection.execute(
                    "SELECT record_json FROM approvals WHERE task_id='task-tamper'"
                ).fetchone()
                payload = json.loads(row["record_json"])
                payload["status"] = "APPROVED"
                payload["approval_event_hash"] = ""
                connection.execute(
                    "UPDATE approvals SET record_json=? WHERE task_id='task-tamper'",
                    (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
                )
            self.assertFalse(gate.can_proceed("task-tamper", "deploy", evidence=["review"], scope="production"))

    def test_empty_evidence_and_rejected_approval_are_blocked(self) -> None:
        gate = ApprovalGate()
        gate.request("task-3", "release", "production", "reviewer", evidence=[])
        self.assertFalse(gate.approve("task-3", approver="reviewer", evidence=[]))
        self.assertEqual(gate.get("task-3").status, ApprovalStatus.BLOCKED)
        gate.request("task-4", "publish", "public", "reviewer", evidence=["review"])
        self.assertTrue(gate.reject("task-4", notes="review declined", approver="reviewer"))
        self.assertFalse(gate.approve("task-4", approver="reviewer", evidence=["review"]))
        self.assertFalse(gate.can_proceed("task-4", "publish", evidence=["review"], scope="public"))

    def test_wrong_approver_cannot_approve(self) -> None:
        gate = ApprovalGate()
        gate.request("task-5", "deploy", "production", "release-manager", evidence=["review"])
        self.assertFalse(gate.approve("task-5", approver="requester", evidence=["review"]))
        self.assertEqual(gate.get("task-5").status, ApprovalStatus.PENDING)
        self.assertTrue(gate.approve("task-5", approver="release-manager", evidence=["review"]))

    def test_action_aliases_and_unknown_actions_are_gated(self) -> None:
        for action in (
            "deployment", "deploy to production", "merge to protected branch",
            "secret_rotation", "external system write", "destructive delete",
            "environment mutation", "run arbitrary shell",
        ):
            with self.subTest(action=action):
                self.assertTrue(ApprovalGate.requires_approval(action))
        self.assertFalse(ApprovalGate.requires_approval("read"))
        self.assertFalse(ApprovalGate.requires_approval("test"))

    def test_new_request_preserves_previous_record(self) -> None:
        gate = ApprovalGate()
        gate.request("task-history", "release", "production", "reviewer", evidence=["v1"])
        self.assertTrue(gate.approve("task-history", approver="reviewer", evidence=["v1"]))
        gate.request("task-history", "release", "production", "reviewer", evidence=["v2"])
        self.assertEqual(len(gate.history("task-history")), 2)
        self.assertEqual(gate.history("task-history")[0].status, ApprovalStatus.APPROVED)
        self.assertEqual(gate.get("task-history").status, ApprovalStatus.PENDING)

    def test_expired_approval_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "approval.sqlite3")
            gate = ApprovalGate(db_path=db_path)
            gate.request("expired", "deploy", "production", "reviewer", evidence=["test report"])
            with gate.store.transaction() as connection:
                row = connection.execute(
                    "SELECT record_json FROM approvals WHERE task_id='expired'"
                ).fetchone()
                payload = json.loads(row["record_json"])
                payload["expires_at"] = "2000-01-01T00:00:00+00:00"
                connection.execute(
                    "UPDATE approvals SET record_json=? WHERE task_id='expired'",
                    (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
                )
            self.assertFalse(gate.approve("expired", approver="reviewer", evidence=["test report"]))
            self.assertEqual(gate.get("expired").status, ApprovalStatus.BLOCKED)

    def test_identity_authorizer_is_required_in_production(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "approval.sqlite3")
            env = {"SWARM_ENV": "production", "SWARM_STATE_DB": db_path, "SWARM_AUDIT_KEY": "k" * 32}
            with patch.dict(os.environ, env):
                gate = ApprovalGate()
                gate.request("prod-approval", "deploy", "production", "idp:user-1", evidence=["review"])
                self.assertFalse(gate.approve("prod-approval", approver="idp:user-1", evidence=["review"]))
                authorized_gate = ApprovalGate(
                    approver_authorizer=lambda actor, record: actor.startswith("idp:") and actor == record.approver
                )
                # Production approvals also need a durable task whose owner made the request.
                authorized_gate.store.append_event("task.created", task_id="prod-authorized", actor="agent:owner")
                with authorized_gate.store.transaction() as connection:
                    connection.execute(
                        "INSERT INTO tasks(task_id, payload_json, updated_at) VALUES(?, ?, ?)",
                        ("prod-authorized", json.dumps({"owner": "agent:owner"}), "now"),
                    )
                authorized_gate.request("prod-authorized", "deploy", "production", "idp:user-1",
                                        evidence=["review"], requester="agent:owner")
                self.assertTrue(
                    authorized_gate.approve("prod-authorized", approver="idp:user-1", evidence=["review"])
                )


class LockRegistryTests(unittest.TestCase):
    def test_parent_directory_and_child_file_conflict(self) -> None:
        registry = LockRegistry()
        self.assertTrue(registry.reserve("src/", "task-a", "owner-a", "directory edit"))
        self.assertFalse(registry.reserve("src/module.py", "task-b", "owner-b", "file edit"))
        self.assertEqual(registry.check("src/module.py").task_id, "task-a")

    def test_lock_objects_are_immutable(self) -> None:
        registry = LockRegistry()
        registry.reserve("src/module.py", "task-a", "owner-a", "file edit")
        lock = registry.check("src/module.py")
        with self.assertRaises(AttributeError):
            lock.owner = "attacker"

    def test_same_owner_nested_paths_and_prefix_siblings(self) -> None:
        registry = LockRegistry()
        self.assertTrue(registry.reserve("src", "task-a", "owner-a", "directory"))
        self.assertTrue(registry.reserve("src/module.py", "task-a", "owner-a", "file"))
        self.assertEqual(registry.list_locks(), {"src", "src/module.py"})
        self.assertTrue(registry.reserve("src-old/file.py", "task-b", "owner-b", "other source"))

    def test_wrong_task_or_owner_cannot_release_lock(self) -> None:
        registry = LockRegistry()
        registry.reserve("src/file.py", "task-a", "owner-a", "edit")
        self.assertFalse(registry.release("src/file.py", "task-b", "owner-b"))
        self.assertFalse(registry.release("src/file.py", "task-a", "owner-b"))
        self.assertTrue(registry.release("src/file.py", "task-a", "owner-a"))

    def test_leased_locks_expire_and_are_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "locks.sqlite3")
            store = SQLiteStateStore(db_path)
            registry = LockRegistry(state_store=store)
            self.assertTrue(registry.reserve("src", "task-a", "owner-a", "leased work", lease_seconds=60))
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE resource_locks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE resource='src'"
                )
            self.assertIsNone(registry.check("src"))
            self.assertTrue(any(e["event_type"] == "lock.lease_expired" for e in store.list_events()))
            self.assertTrue(store.verify_audit_chain()["valid"])

    def test_locks_are_shared_across_registry_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "shared.sqlite3")
            first = LockRegistry(db_path=db_path)
            second = LockRegistry(db_path=db_path)
            self.assertTrue(first.reserve("src/main.py", "task-a", "owner-a", "edit"))
            self.assertFalse(second.reserve("src/main.py", "task-b", "owner-b", "edit"))
            self.assertTrue(second.release("src/main.py", "task-a", "owner-a"))


class EvidenceAndStateTests(unittest.TestCase):
    def test_registry_defensively_copies_evidence_objects(self) -> None:
        registry = EvidenceRegistry()
        bundle = EvidenceBundle(task_id="task-copy", title="source", content="verified fact")
        registry.add(bundle)
        bundle.status = EvidenceStatus.VERIFIED
        self.assertFalse(registry.is_verified("task-copy"))
        returned = registry.get("task-copy")
        returned[0].status = EvidenceStatus.VERIFIED
        self.assertFalse(registry.is_verified("task-copy"))
        registry.mark_verified("task-copy")
        self.assertTrue(registry.is_verified("task-copy"))

    def test_rejected_evidence_cannot_be_reverified(self) -> None:
        registry = EvidenceRegistry()
        registry.add(EvidenceBundle(task_id="task-e", title="claim", content="disputed"))
        registry.mark_rejected("task-e")
        registry.mark_verified("task-e")
        self.assertEqual(registry.get("task-e")[0].status, EvidenceStatus.REJECTED)
        self.assertFalse(registry.is_verified("task-e"))

    def test_release_state_requires_evidence_and_explicit_approval(self) -> None:
        task = TaskRecord(
            task_id="task-release", owner="owner", objective="release safely", evidence=["build-log"]
        )
        registry = EvidenceRegistry()
        registry.add(EvidenceBundle(task_id=task.task_id, title="build-log", content="tests passed"))
        for state in (
            TaskStatus.GROUNDED, TaskStatus.PLANNED, TaskStatus.READY,
            TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING,
        ):
            TaskStateMachine.transition(task, state)

        with self.assertRaisesRegex(ValueError, "Verified evidence"):
            TaskStateMachine.transition(task, TaskStatus.READY_FOR_RELEASE, evidence_registry=registry)
        registry.mark_verified(task.task_id)
        task.evidence = ["unrelated-reference"]
        with self.assertRaisesRegex(ValueError, "match verified evidence records"):
            TaskStateMachine.transition(task, TaskStatus.READY_FOR_RELEASE, evidence_registry=registry)
        task.evidence = ["build-log"]
        TaskStateMachine.transition(task, TaskStatus.READY_FOR_RELEASE, evidence_registry=registry)

        with self.assertRaisesRegex(ValueError, "pending approval request"):
            TaskStateMachine.transition(task, TaskStatus.AWAITING_APPROVAL)
        gate = ReleaseGate()
        gate.request(task.task_id, "release", "production", "reviewer", evidence=task.evidence)
        TaskStateMachine.transition(
            task, TaskStatus.AWAITING_APPROVAL, approval_gate=gate, approval_scope="production"
        )
        with self.assertRaisesRegex(ValueError, "Release is blocked"):
            TaskStateMachine.transition(task, TaskStatus.RELEASED, approval_gate=gate, approval_scope="production")
        self.assertTrue(gate.approve(task.task_id, approver="reviewer", evidence=task.evidence))
        TaskStateMachine.transition(task, TaskStatus.RELEASED, approval_gate=gate, approval_scope="production")
        self.assertEqual(task.status, TaskStatus.RELEASED)

    def test_blocked_task_requires_unblock_justification(self) -> None:
        task = TaskRecord(
            task_id="blocked", owner="owner", objective="unblock",
            status=TaskStatus.BLOCKED, blocked_from=TaskStatus.IN_PROGRESS.value,
        )
        with self.assertRaisesRegex(ValueError, "justification"):
            TaskStateMachine.transition(task, TaskStatus.IN_PROGRESS)
        TaskStateMachine.transition(task, TaskStatus.IN_PROGRESS, justification="dependency restored")
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_terminal_task_cannot_be_blocked_again(self) -> None:
        task = TaskRecord(task_id="closed", owner="owner", objective="closed", status=TaskStatus.CLOSED)
        with self.assertRaisesRegex(ValueError, "terminal task"):
            TaskStateMachine.add_blocker(task, "late blocker")


class BenchmarkTests(unittest.TestCase):
    def test_evidence_score_requires_verified_evidence(self) -> None:
        runner = BenchmarkRunner()
        task = TaskRecord(
            task_id="bench-evidence", owner="owner", objective="measure evidence",
            status=TaskStatus.READY, evidence=["build-log"],
        )
        runner.add_evidence(task.task_id, EvidenceBundle(task_id=task.task_id, title="build-log", content="test output"))
        self.assertEqual(runner.run_core_task(task).evidence_score, 0)
        runner.registry.mark_verified(task.task_id)
        result = runner.run_core_task(task)
        self.assertEqual(result.evidence_score, 100)
        self.assertEqual(result.total, 100)

    def test_benchmark_rejects_mismatched_evidence_task_id(self) -> None:
        runner = BenchmarkRunner()
        with self.assertRaisesRegex(ValueError, "must match"):
            runner.add_evidence("task-a", EvidenceBundle(task_id="task-b", title="log", content="output"))

    def test_release_ready_task_without_verified_evidence_is_penalized(self) -> None:
        runner = BenchmarkRunner()
        task = TaskRecord(
            task_id="bench-release", owner="owner", objective="release score",
            status=TaskStatus.READY_FOR_RELEASE, evidence=["build-log"],
        )
        result = runner.run_core_task(task)
        self.assertEqual(result.evidence_score, 0)
        self.assertEqual(result.safety_score, 0)
        self.assertEqual(result.benchmark_score, 0)


class TaskBoardTests(unittest.TestCase):
    def test_round_trip_and_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.json"
            board = TaskBoard(str(path))
            task = TaskRecord(
                task_id="round-trip", owner="owner", objective="persist state", status=TaskStatus.BLOCKED
            )
            task.blockers = ["waiting for approval"]
            task.evidence = ["partial proof"]
            board.add_or_update(task)
            recovered = board.get("round-trip")
            self.assertEqual(recovered.status, TaskStatus.BLOCKED.value)
            self.assertEqual(recovered.blockers, ["waiting for approval"])
            self.assertEqual(recovered.evidence, ["partial proof"])
            self.assertEqual(list(Path(directory).glob(".board.json.*.tmp")), [])

    def test_corrupt_board_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                TaskBoard(str(path)).load()

    def test_invalid_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.json"
            path.write_text(json.dumps({"task": {"task_id": "task", "status": "COMPLETE"}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid task status"):
                TaskBoard(str(path)).load()

    def test_sqlite_board_persists_between_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "tasks.sqlite3")
            board = TaskBoard(db_path=db_path)
            task = TaskRecord(task_id="persistent-task", owner="owner", objective="persist", status=TaskStatus.BLOCKED)
            task.blockers = ["external approval"]
            board.add_or_update(task)
            restored = TaskBoard(db_path=db_path).get("persistent-task")
            self.assertEqual(restored.status, TaskStatus.BLOCKED.value)
            self.assertEqual(restored.blockers, ["external approval"])


class RepoGroundingTests(unittest.TestCase):
    def test_package_manifest_does_not_invent_test_or_build_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"name": "demo"}), encoding="utf-8")
            commands = RepoGroundingEngine(directory)._discover_commands(["package.json"])
            self.assertIn("npm install", commands)
            self.assertNotIn("npm test", commands)
            self.assertNotIn("npm run build", commands)

    def test_package_scripts_are_discovered_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps({"name": "demo", "scripts": {"test": "vitest run", "build": "vite build"}}),
                encoding="utf-8",
            )
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            commands = RepoGroundingEngine(directory)._discover_commands(["package.json"])
            self.assertIn("npm test", commands)
            self.assertIn("npm run build", commands)
            self.assertIn("npm ci", commands)
            self.assertNotIn("npm install", commands)


class StorageTests(unittest.TestCase):
    def test_approval_and_evidence_survive_store_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "shared.sqlite3")
            first = ApprovalGate(db_path=db_path)
            evidence = ["release checklist"]
            first.request("task-shared", "deploy", "production", "reviewer", evidence=evidence)
            second = ApprovalGate(db_path=db_path)
            self.assertEqual(second.get("task-shared").status, ApprovalStatus.PENDING)
            self.assertTrue(second.approve("task-shared", approver="reviewer", evidence=evidence))
            self.assertTrue(first.can_proceed("task-shared", "deploy", evidence=evidence, scope="production"))

            evidence_store = EvidenceRegistry(db_path=db_path)
            evidence_store.add(EvidenceBundle(task_id="task-shared", title="release checklist", content="verified"))
            reopened = EvidenceRegistry(db_path=db_path)
            self.assertEqual(reopened.get("task-shared")[0].content, "verified")
            reopened.mark_verified("task-shared")
            self.assertTrue(evidence_store.is_verified("task-shared"))

            verifier = SQLiteStateStore(db_path)
            self.assertTrue(verifier.verify_audit_chain()["valid"])

    def test_audit_chain_detects_event_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "audit.sqlite3")
            store = SQLiteStateStore(db_path)
            store.append_event("audit.test", payload={"detail": "original"})
            self.assertTrue(store.verify_audit_chain()["valid"])
            with sqlite3.connect(db_path) as connection:
                connection.execute("DROP TRIGGER IF EXISTS audit_events_no_update")
                connection.execute("UPDATE audit_events SET payload_json='{}' WHERE sequence=1")
            result = store.verify_audit_chain()
            self.assertFalse(result["valid"])
            self.assertIn("hash mismatch", result["error"])

    def test_production_requires_durable_database_path(self) -> None:
        with patch.dict(os.environ, {"SWARM_ENV": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SWARM_STATE_DB"):
                SQLiteStateStore()

    def test_database_file_permissions_are_restricted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restricted.sqlite3"
            SQLiteStateStore(str(path))
            mode = stat.S_IMODE(path.stat().st_mode)
            if os.name == "posix":
                self.assertEqual(mode, 0o600)

    def test_malformed_or_tampered_approval_cannot_proceed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "approval.sqlite3")
            gate = ApprovalGate(db_path=db_path)
            gate.request("tampered", "deploy", "production", "reviewer", evidence=["test"])
            with gate.store.transaction() as connection:
                row = connection.execute("SELECT record_json FROM approvals WHERE task_id='tampered'").fetchone()
                payload = json.loads(row["record_json"])
                payload["status"] = "APPROVED"
                payload["approval_event_hash"] = ""
                connection.execute(
                    "UPDATE approvals SET record_json=? WHERE task_id='tampered'",
                    (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
                )
            self.assertFalse(gate.can_proceed("tampered", "deploy", evidence=["test"], scope="production"))


class IntegratedValidationTests(unittest.TestCase):
    def test_documented_full_validation_passes(self) -> None:
        results = run_full_validation()
        failures = [f"{result.name}: {result.details}" for result in results if not result.passed]
        self.assertEqual(failures, [])

    def test_release_gate_export_is_available(self) -> None:
        self.assertTrue(finalize_release_gate().passed)


if __name__ == "__main__":
    unittest.main()
