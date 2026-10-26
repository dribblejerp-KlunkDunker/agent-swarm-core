"""Regression tests for the hardening pass: one class per fixed weakness."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.approval import ApprovalGate, _canonical_action
from runtime.locks import DEFAULT_LEASE_SECONDS, LockRegistry
from runtime.repo_grounding import RepoGroundingEngine
from runtime.storage import SQLiteStateStore
from runtime.task_board import TaskBoard
from runtime.task_state import TaskRecord, TaskStateMachine, TaskStatus

AUDIT_KEY = "test-audit-key-0123456789abcdef0123"


class CompoundActionTests(unittest.TestCase):
    def test_single_category_aliases_still_match(self) -> None:
        self.assertEqual(_canonical_action("deployment"), "deploy")
        self.assertEqual(_canonical_action("merge to protected branch"), "merge")
        self.assertEqual(_canonical_action("destructive delete"), "destructive-action")

    def test_multi_category_actions_become_compound(self) -> None:
        self.assertEqual(_canonical_action("merge-and-deploy-to-production"), "compound:deploy+merge")
        self.assertEqual(_canonical_action("merge then delete prod db"), "compound:destructive-action+merge")
        self.assertTrue(ApprovalGate.requires_approval("merge and deploy"))

    def test_approved_merge_does_not_authorise_compound_action(self) -> None:
        gate = ApprovalGate()
        gate.request("t", "merge", "main", "approver", evidence=["review"])
        self.assertTrue(gate.approve("t", approver="approver", evidence=["review"]))
        self.assertTrue(gate.can_proceed("t", "merge", evidence=["review"], scope="main"))
        for action in ("merge-and-deploy-to-production", "merge then delete prod db", "force merge"):
            with self.subTest(action=action):
                self.assertFalse(gate.can_proceed("t", action, evidence=["review"], scope="main"))

    def test_compound_action_can_be_approved_explicitly(self) -> None:
        gate = ApprovalGate()
        gate.request("t", "merge and deploy", "production", "approver", evidence=["review"])
        gate.approve("t", approver="approver", evidence=["review"])
        self.assertTrue(gate.can_proceed("t", "deploy-and-merge", evidence=["review"], scope="production"))


class SeparationOfDutiesTests(unittest.TestCase):
    def test_requester_cannot_name_themselves_approver(self) -> None:
        with self.assertRaisesRegex(ValueError, "Separation of duties"):
            ApprovalGate().request("t", "deploy", "prod", "alice", evidence=["e"], requester="alice")

    def test_tampered_record_where_requester_approves_is_denied(self) -> None:
        gate = ApprovalGate()
        gate.request("t", "deploy", "prod", "bob", evidence=["e"], requester="alice")
        with gate.store.transaction() as connection:
            row = connection.execute("SELECT record_json FROM approvals WHERE task_id='t'").fetchone()
            connection.execute(
                "UPDATE approvals SET record_json=? WHERE task_id='t'",
                (row["record_json"].replace('"approver":"bob"', '"approver":"alice"'),),
            )
        self.assertFalse(gate.approve("t", approver="alice", evidence=["e"]))
        reasons = [e["payload"].get("reason") for e in gate.store.list_events() if e["event_type"] == "approval.denied"]
        self.assertIn("separation_of_duties", reasons)


class UnblockTests(unittest.TestCase):
    def test_unblock_returns_at_most_to_origin(self) -> None:
        task = TaskRecord(task_id="t", owner="o", objective="x")
        TaskStateMachine.transition(task, TaskStatus.GROUNDED)
        TaskStateMachine.add_blocker(task, "dep")
        self.assertEqual(task.blocked_from, "GROUNDED")
        for target in (TaskStatus.PLANNED, TaskStatus.READY, TaskStatus.IN_PROGRESS):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "may only resume to"):
                    TaskStateMachine.transition(task, target, justification="fixed")
        TaskStateMachine.transition(task, TaskStatus.INTAKE, justification="re-ground from scratch")
        self.assertEqual(task.status, TaskStatus.INTAKE)
        self.assertEqual(task.blockers, [])

    def test_late_stage_block_resumes_no_later_than_in_progress(self) -> None:
        task = TaskRecord(task_id="t", owner="o", objective="x", status=TaskStatus.VERIFYING)
        TaskStateMachine.add_blocker(task, "flaky test")
        TaskStateMachine.transition(task, TaskStatus.IN_PROGRESS, justification="test fixed")
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_cancel_keeps_blockers_for_the_record(self) -> None:
        task = TaskRecord(task_id="t", owner="o", objective="x")
        TaskStateMachine.add_blocker(task, "won't fix")
        TaskStateMachine.transition(task, TaskStatus.CANCELLED)
        self.assertEqual(task.blockers, ["won't fix"])

    def test_transition_to_blocked_records_origin(self) -> None:
        task = TaskRecord(task_id="t", owner="o", objective="x", status=TaskStatus.READY)
        TaskStateMachine.transition(task, TaskStatus.BLOCKED)
        self.assertEqual(task.blocked_from, "READY")


class LockLeaseTests(unittest.TestCase):
    def test_locks_are_leased_by_default(self) -> None:
        registry = LockRegistry()
        registry.reserve("src", "t", "o", "edit")
        self.assertIsNotNone(registry.check("src").lease_expires_at)
        self.assertEqual(DEFAULT_LEASE_SECONDS, 1800)

    def test_permanent_lock_is_dev_only(self) -> None:
        self.assertTrue(LockRegistry().reserve("src", "t", "o", "edit", lease_seconds=None))
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "locks.sqlite3")
            env = {"SWARM_ENV": "production", "SWARM_STATE_DB": db, "SWARM_AUDIT_KEY": AUDIT_KEY}
            with patch.dict(os.environ, env, clear=True):
                registry = LockRegistry()
                with self.assertRaisesRegex(ValueError, "not allowed in production"):
                    registry.reserve("src", "t", "o", "edit", lease_seconds=None)
                self.assertTrue(registry.reserve("src", "t", "o", "edit"))


class DirectBoardWriteTests(unittest.TestCase):
    def test_direct_board_writes_are_refused_in_production(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "tasks.sqlite3")
            env = {"SWARM_ENV": "production", "SWARM_STATE_DB": db, "SWARM_AUDIT_KEY": AUDIT_KEY}
            with patch.dict(os.environ, env, clear=True):
                board = TaskBoard()
                task = TaskRecord(task_id="t", owner="o", objective="x", status=TaskStatus.AWAITING_APPROVAL)
                with self.assertRaisesRegex(RuntimeError, "use RuntimeServices"):
                    board.add_or_update(task)
                with self.assertRaisesRegex(RuntimeError, "use RuntimeServices"):
                    board.save({})

    def test_dev_direct_writes_are_marked_unchecked(self) -> None:
        board = TaskBoard(db_path=":memory:")
        board.add_or_update(TaskRecord(task_id="t", owner="o", objective="x"))
        events = board._store.list_events()
        self.assertFalse(events[-1]["payload"]["lifecycle_checked"])


class KeyedAuditChainTests(unittest.TestCase):
    def test_keyed_chain_needs_key_to_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "audit.sqlite3")
            store = SQLiteStateStore(db, audit_key=AUDIT_KEY)
            store.append_event("e", payload={"n": 1})
            self.assertEqual(store.audit_mode, "hmac-sha256")
            self.assertTrue(store.verify_audit_chain()["valid"])
            with self.assertRaisesRegex(RuntimeError, "keyed audit chain"):
                SQLiteStateStore(db)
            wrong_key = SQLiteStateStore(db, audit_key="w" * 32)
            self.assertFalse(wrong_key.verify_audit_chain()["valid"])

    def test_unkeyed_history_is_not_silently_rekeyed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "audit.sqlite3")
            SQLiteStateStore(db).append_event("e")
            with self.assertRaisesRegex(RuntimeError, "unkeyed audit chain"):
                SQLiteStateStore(db, audit_key=AUDIT_KEY)

    def test_empty_unkeyed_database_upgrades_to_keyed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "audit.sqlite3")
            SQLiteStateStore(db)
            keyed = SQLiteStateStore(db, audit_key=AUDIT_KEY)
            keyed.append_event("e")
            self.assertTrue(keyed.verify_audit_chain()["valid"])

    def test_short_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 32"):
            SQLiteStateStore(audit_key="short")

    def test_anchor_detects_truncation_and_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "audit.sqlite3")
            store = SQLiteStateStore(db)
            store.append_event("e", payload={"n": 1})
            store.append_event("e", payload={"n": 2})
            anchor = store.audit_checkpoint()
            self.assertTrue(store.verify_audit_chain(anchor=anchor)["valid"])
            connection = sqlite3.connect(db)
            connection.execute("DROP TRIGGER audit_events_no_delete")
            connection.execute("DELETE FROM audit_events WHERE sequence=2")
            connection.commit()
            connection.close()
            self.assertTrue(store.verify_audit_chain()["valid"])  # the chain alone cannot see it
            result = store.verify_audit_chain(anchor=anchor)
            self.assertFalse(result["valid"])
            self.assertIn("truncated", result["error"])

    def test_approval_check_verifies_chain_once(self) -> None:
        gate = ApprovalGate()
        gate.request("t", "deploy", "prod", "approver", evidence=["e"])
        gate.approve("t", approver="approver", evidence=["e"])
        with patch.object(gate.store, "_verify_chain_links", wraps=gate.store._verify_chain_links) as spy:
            self.assertTrue(gate.can_proceed("t", "deploy", evidence=["e"], scope="prod"))
        self.assertEqual(spy.call_count, 1)


class SchemaMigrationTests(unittest.TestCase):
    def test_version_2_database_migrates_and_keeps_its_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "legacy.sqlite3")
            store = SQLiteStateStore(db)
            store.append_event("legacy.event", payload={"kept": True})
            connection = sqlite3.connect(db)
            connection.execute("DELETE FROM metadata WHERE key='audit_hash_mode'")
            connection.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
            connection.commit()
            connection.close()
            migrated = SQLiteStateStore(db)
            with migrated.read_connection() as conn:
                values = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            self.assertEqual(values["schema_version"], "3")
            self.assertEqual(values["audit_hash_mode"], "sha256")
            self.assertTrue(migrated.verify_audit_chain()["valid"])

    def test_newer_schema_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "future.sqlite3")
            SQLiteStateStore(db)
            connection = sqlite3.connect(db)
            connection.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                SQLiteStateStore(db)


class GroundingNoiseTests(unittest.TestCase):
    def test_ordinary_words_are_not_risks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "README.md").write_text(
                "Author: someone. This tokenizer reads published papers.\n", encoding="utf-8"
            )
            self.assertEqual(RepoGroundingEngine(directory)._detect_risks(), [])

    def test_real_risk_terms_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "app.py").write_text(
                "import subprocess\nOAUTH login with api_key\n", encoding="utf-8"
            )
            risks = RepoGroundingEngine(directory)._detect_risks()
            self.assertIn("Potential risk area: auth", risks)
            self.assertIn("Potential risk area: secret", risks)
            self.assertIn("Potential risk area: shell", risks)


class GodotGroundingTests(unittest.TestCase):
    def test_godot_project_and_headless_runners_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "smoke_test.gd").write_text("# runner\nextends SceneTree\n", encoding="utf-8")
            (root / "player.gd").write_text("extends CharacterBody3D\n", encoding="utf-8")
            facts = RepoGroundingEngine(directory).inspect()
            self.assertEqual(facts.project_type, "godot")
            self.assertIn("godot --headless --path . --import", facts.commands)
            self.assertIn("godot --headless --path . --script res://tests/smoke_test.gd", facts.commands)
            self.assertFalse(any("player.gd" in command for command in facts.commands))

if __name__ == "__main__":
    unittest.main()
