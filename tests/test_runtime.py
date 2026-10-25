from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime import finalize_release_gate
from runtime.approval import ApprovalGate, ApprovalStatus, ReleaseGate
from runtime.evidence import EvidenceBundle, EvidenceRegistry, EvidenceStatus
from runtime.locks import LockRegistry
from runtime.repo_grounding import RepoGroundingEngine
from runtime.task_board import TaskBoard, TaskBoardEntry
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

    def test_approval_is_bound_to_action_scope_and_evidence(self) -> None:
        gate = ApprovalGate()
        evidence = ["test log", "diff"]
        gate.request("task-2", "deploy", "production", "reviewer", evidence=evidence)
        self.assertTrue(gate.approve("task-2"))

        self.assertFalse(gate.can_proceed("task-2", "publish", evidence=evidence, scope="production"))
        self.assertFalse(gate.can_proceed("task-2", "deploy", evidence=evidence, scope="staging"))
        self.assertFalse(gate.can_proceed("task-2", "deploy", evidence=["changed log"], scope="production"))
        self.assertEqual(gate.get("task-2").status, ApprovalStatus.BLOCKED)

    def test_empty_evidence_and_rejected_approval_are_blocked(self) -> None:
        gate = ApprovalGate()
        gate.request("task-3", "release", "production", "reviewer", evidence=[])
        self.assertFalse(gate.approve("task-3"))
        self.assertEqual(gate.get("task-3").status, ApprovalStatus.BLOCKED)

        gate.request("task-4", "publish", "public", "reviewer", evidence=["review"])
        self.assertTrue(gate.reject("task-4", "review declined"))
        self.assertFalse(gate.approve("task-4"))
        self.assertFalse(gate.can_proceed("task-4", "publish", evidence=["review"], scope="public"))

    def test_action_aliases_cannot_bypass_approval(self) -> None:
        for action in (
            "deployment",
            "deploy to production",
            "merge to protected branch",
            "secret_rotation",
            "external system write",
            "destructive delete",
            "environment mutation",
        ):
            with self.subTest(action=action):
                self.assertTrue(ApprovalGate.requires_approval(action))

    def test_new_request_preserves_previous_approval_record(self) -> None:
        gate = ApprovalGate()
        gate.request("task-history", "release", "production", "reviewer", evidence=["v1"])
        self.assertTrue(gate.approve("task-history"))
        gate.request("task-history", "release", "production", "reviewer", evidence=["v2"])
        self.assertEqual(len(gate.history("task-history")), 2)
        self.assertEqual(gate.history("task-history")[0].status, ApprovalStatus.APPROVED)
        self.assertEqual(gate.get("task-history").status, ApprovalStatus.PENDING)


class LockRegistryTests(unittest.TestCase):
    def test_parent_directory_and_child_file_conflict_across_tasks(self) -> None:
        registry = LockRegistry()
        self.assertTrue(registry.reserve("src/", "task-a", "owner-a", "directory edit"))
        self.assertFalse(registry.reserve("src/module.py", "task-b", "owner-b", "file edit"))
        self.assertEqual(registry.check("src/module.py").task_id, "task-a")

    def test_same_owner_can_reserve_nested_paths(self) -> None:
        registry = LockRegistry()
        self.assertTrue(registry.reserve("src", "task-a", "owner-a", "directory"))
        self.assertTrue(registry.reserve("src/module.py", "task-a", "owner-a", "file"))
        self.assertEqual(registry.list_locks(), {"src", "src/module.py"})

    def test_path_prefixes_do_not_cause_false_conflicts(self) -> None:
        registry = LockRegistry()
        self.assertTrue(registry.reserve("src", "task-a", "owner-a", "source"))
        self.assertTrue(registry.reserve("src-old/file.py", "task-b", "owner-b", "other source"))

    def test_wrong_task_cannot_release_lock(self) -> None:
        registry = LockRegistry()
        registry.reserve("src/file.py", "task-a", "owner-a", "edit")
        self.assertFalse(registry.release("src/file.py", "task-b"))
        self.assertTrue(registry.release("src/file.py", "task-a"))


class EvidenceAndStateTests(unittest.TestCase):
    def test_rejected_evidence_cannot_be_reverified_by_mark_verified(self) -> None:
        registry = EvidenceRegistry()
        registry.add(EvidenceBundle(task_id="task-e", title="claim", content="disputed"))
        registry.mark_rejected("task-e")
        registry.mark_verified("task-e")
        self.assertEqual(registry.get("task-e")[0].status, EvidenceStatus.REJECTED)
        self.assertFalse(registry.is_verified("task-e"))

    def test_release_state_requires_verified_evidence_and_explicit_approval(self) -> None:
        task = TaskRecord(
            task_id="task-release",
            owner="owner",
            objective="release safely",
            evidence=["build-log"],
        )
        registry = EvidenceRegistry()
        registry.add(EvidenceBundle(task_id=task.task_id, title="build-log", content="tests passed"))

        for state in (
            TaskStatus.GROUNDED,
            TaskStatus.PLANNED,
            TaskStatus.READY,
            TaskStatus.IN_PROGRESS,
            TaskStatus.VERIFYING,
        ):
            TaskStateMachine.transition(task, state)

        with self.assertRaisesRegex(ValueError, "Verified evidence"):
            TaskStateMachine.transition(task, TaskStatus.READY_FOR_RELEASE, evidence_registry=registry)

        registry.mark_verified(task.task_id)
        TaskStateMachine.transition(task, TaskStatus.READY_FOR_RELEASE, evidence_registry=registry)
        TaskStateMachine.transition(task, TaskStatus.AWAITING_APPROVAL)

        gate = ReleaseGate()
        gate.request(task.task_id, "release", "production", "reviewer", evidence=task.evidence)
        with self.assertRaisesRegex(ValueError, "Release is blocked"):
            TaskStateMachine.transition(
                task,
                TaskStatus.RELEASED,
                approval_gate=gate,
                approval_scope="production",
            )
        self.assertTrue(gate.approve(task.task_id))
        TaskStateMachine.transition(
            task,
            TaskStatus.RELEASED,
            approval_gate=gate,
            approval_scope="production",
        )
        self.assertEqual(task.status, TaskStatus.RELEASED)

    def test_blocked_task_requires_unblock_justification(self) -> None:
        task = TaskRecord(task_id="blocked", owner="owner", objective="unblock", status=TaskStatus.BLOCKED)
        with self.assertRaisesRegex(ValueError, "justification"):
            TaskStateMachine.transition(task, TaskStatus.IN_PROGRESS)
        TaskStateMachine.transition(task, TaskStatus.IN_PROGRESS, justification="dependency restored")
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_terminal_task_cannot_be_blocked_again(self) -> None:
        task = TaskRecord(task_id="closed", owner="owner", objective="closed", status=TaskStatus.CLOSED)
        with self.assertRaisesRegex(ValueError, "terminal task"):
            TaskStateMachine.add_blocker(task, "late blocker")


class TaskBoardTests(unittest.TestCase):
    def test_round_trip_and_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.json"
            board = TaskBoard(str(path))
            task = TaskRecord(
                task_id="round-trip",
                owner="owner",
                objective="persist state",
                status=TaskStatus.BLOCKED,
            )
            task.blockers = ["waiting for approval"]
            task.evidence = ["partial proof"]
            board.add_or_update(task)

            recovered = board.get("round-trip")
            self.assertEqual(recovered.status, TaskStatus.BLOCKED.value)
            self.assertEqual(recovered.blockers, ["waiting for approval"])
            self.assertEqual(recovered.evidence, ["partial proof"])
            self.assertEqual(list(Path(directory).glob(".board.json.*.tmp")), [])

    def test_corrupt_board_fails_closed_instead_of_returning_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                TaskBoard(str(path)).load()

    def test_invalid_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.json"
            path.write_text(json.dumps({"task": {"task_id": "task", "status": "COMPLETE"}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid status"):
                TaskBoard(str(path)).load()


class RepoGroundingTests(unittest.TestCase):
    def test_package_manifest_does_not_invent_test_or_build_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"name": "demo"}), encoding="utf-8")
            engine = RepoGroundingEngine(directory)
            commands = engine._discover_commands(["package.json"])
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


class IntegratedValidationTests(unittest.TestCase):
    def test_documented_full_validation_passes(self) -> None:
        results = run_full_validation()
        failures = [f"{result.name}: {result.details}" for result in results if not result.passed]
        self.assertEqual(failures, [])

    def test_release_gate_export_is_available(self) -> None:
        self.assertTrue(finalize_release_gate().passed)


if __name__ == "__main__":
    unittest.main()
