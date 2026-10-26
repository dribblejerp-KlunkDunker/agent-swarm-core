from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.evidence import EvidenceBundle
from runtime.services import RuntimeServices
from runtime.task_state import TaskRecord, TaskStatus

AUDIT_KEY = "test-audit-key-0123456789abcdef0123"


def _production_env(db_path: str) -> dict:
    return {"SWARM_ENV": "production", "SWARM_STATE_DB": db_path, "SWARM_AUDIT_KEY": AUDIT_KEY}


class RuntimeServicesTests(unittest.TestCase):
    def _production_services(self, db_path: str) -> RuntimeServices:
        return RuntimeServices(
            db_path=db_path,
            approver_authorizer=lambda actor, record: actor == record.approver == "idp:approver",
            evidence_authorizer=lambda actor, bundle: actor == "idp:reviewer" and bundle.task_id == "deploy-task",
        )

    def _advance_to_awaiting_approval(self, services: RuntimeServices, task: TaskRecord) -> None:
        services.create_task(task)
        for status in (TaskStatus.GROUNDED, TaskStatus.PLANNED, TaskStatus.READY,
                       TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING):
            services.transition_task(task, status)
        services.evidence.add(EvidenceBundle(task_id=task.task_id, title="build-log",
                                             content="CI tests passed", source="ci"))
        self.assertTrue(services.evidence.mark_verified(task.task_id, verifier="idp:reviewer"))
        services.transition_task(task, TaskStatus.READY_FOR_RELEASE)
        services.request_approval(task, scope="production", approver="idp:approver")
        services.transition_task(task, TaskStatus.AWAITING_APPROVAL, approval_scope="production")

    def _deploy_task(self) -> TaskRecord:
        return TaskRecord(
            task_id="deploy-task", owner="worker", objective="safe deploy", evidence=["build-log"],
            approval_action="deploy", repo="demo/service", branch="release", risk_level="HIGH",
            required_skills=["project-grounding", "evidence-auditor"],
        )

    def test_production_lifecycle_persists_state_and_gates_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "runtime.sqlite3")
            with patch.dict(os.environ, _production_env(db), clear=True):
                services = self._production_services(db)
                task = self._deploy_task()
                self._advance_to_awaiting_approval(services, task)
                self.assertFalse(services.can_perform_action(task.task_id, "deploy", scope="staging", evidence=task.evidence))
                self.assertTrue(services.approvals.approve(task.task_id, approver="idp:approver", evidence=task.evidence))
                self.assertTrue(services.can_perform_action(task.task_id, "deploy", scope="production", evidence=task.evidence))
                services.transition_task(task, TaskStatus.RELEASED, approval_scope="production")
                self.assertEqual(services.load_task(task.task_id).status, TaskStatus.RELEASED)
                self.assertTrue(services.store.verify_task_status(task.task_id, "RELEASED"))
                self.assertTrue(services.health_check().ready)

    def test_production_refuses_approval_without_recorded_requester(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "runtime.sqlite3")
            with patch.dict(os.environ, _production_env(db), clear=True):
                services = self._production_services(db)
                task = self._deploy_task()
                self._advance_to_awaiting_approval(services, task)
                # Re-request directly on the gate, without a requester, so separation of duties is unknown.
                services.approvals.request(task.task_id, "deploy", "production", "idp:approver", evidence=task.evidence)
                self.assertTrue(services.approvals.approve(task.task_id, approver="idp:approver", evidence=task.evidence))
                self.assertFalse(services.can_perform_action(task.task_id, "deploy", scope="production", evidence=task.evidence))
                reasons = [e["payload"].get("reason") for e in services.store.list_events() if e["event_type"] == "action.denied"]
                self.assertIn("separation_of_duties_unverified", reasons)

    def test_task_blocked_during_lifecycle_can_still_release_in_production(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "runtime.sqlite3")
            with patch.dict(os.environ, _production_env(db), clear=True):
                services = self._production_services(db)
                task = self._deploy_task()
                services.create_task(task)
                services.transition_task(task, TaskStatus.GROUNDED)
                services.add_blocker(task, "waiting on fixture")
                self.assertEqual(task.blocked_from, "GROUNDED")
                with self.assertRaisesRegex(ValueError, "may only resume to"):
                    services.transition_task(task, TaskStatus.IN_PROGRESS, justification="fixed")
                services.transition_task(task, TaskStatus.GROUNDED, justification="fixture restored")
                self.assertEqual(task.blockers, [])
                for status in (TaskStatus.PLANNED, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING):
                    services.transition_task(task, status)
                services.evidence.add(EvidenceBundle(task_id=task.task_id, title="build-log", content="ok"))
                services.evidence.mark_verified(task.task_id, verifier="idp:reviewer")
                services.transition_task(task, TaskStatus.READY_FOR_RELEASE)
                services.request_approval(task, scope="production", approver="idp:approver")
                services.transition_task(task, TaskStatus.AWAITING_APPROVAL, approval_scope="production")
                self.assertTrue(services.approvals.approve(task.task_id, approver="idp:approver", evidence=task.evidence))
                # The audit replay must follow task.blocker_added, or this would be denied.
                self.assertTrue(services.can_perform_action(task.task_id, "deploy", scope="production", evidence=task.evidence))

    def test_production_fails_closed_without_database_key_or_identity_adapters(self):
        with patch.dict(os.environ, {"SWARM_ENV": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SWARM_STATE_DB"):
                RuntimeServices()
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "state.sqlite3")
            with patch.dict(os.environ, {"SWARM_ENV": "production", "SWARM_STATE_DB": db}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "SWARM_AUDIT_KEY"):
                    RuntimeServices(db_path=db)
            with patch.dict(os.environ, _production_env(db), clear=True):
                with self.assertRaisesRegex(RuntimeError, "approver_authorizer"):
                    RuntimeServices(db_path=db)
                with self.assertRaisesRegex(RuntimeError, "evidence_authorizer"):
                    RuntimeServices(db_path=db, approver_authorizer=lambda actor, record: True)

    def test_owner_cannot_be_approver(self):
        services = RuntimeServices()
        task = TaskRecord(task_id="self", owner="worker", objective="no self approval", evidence=["log"])
        services.create_task(task)
        with self.assertRaisesRegex(ValueError, "Separation of duties"):
            services.request_approval(task, scope="production", approver="worker")

    def test_blockers_and_evidence_references_are_persisted_and_audited(self):
        services = RuntimeServices()
        task = TaskRecord(task_id="mutations", owner="owner", objective="persist task mutations")
        services.create_task(task)
        self.assertTrue(services.add_evidence_reference(task, "build-log"))
        self.assertFalse(services.add_evidence_reference(task, "build-log"))
        self.assertEqual(services.load_task(task.task_id).evidence, ["build-log"])
        services.add_blocker(task, "missing fixture")
        restored = services.load_task(task.task_id)
        self.assertEqual(restored.status, TaskStatus.BLOCKED)
        self.assertEqual(restored.blockers, ["missing fixture"])
        self.assertEqual(restored.blocked_from, "INTAKE")
        event_types = [event["event_type"] for event in services.store.list_events()]
        self.assertIn("task.evidence_reference_added", event_types)
        self.assertIn("task.blocker_added", event_types)

    def test_evidence_reference_cannot_change_after_release_readiness(self):
        services = RuntimeServices()
        task = TaskRecord(task_id="sealed-evidence", owner="owner", objective="seal refs")
        services.create_task(task)
        for status in (TaskStatus.GROUNDED, TaskStatus.PLANNED, TaskStatus.READY,
                       TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING):
            services.transition_task(task, status)
        services.evidence.add(EvidenceBundle(task_id=task.task_id, title="build-log", content="test evidence"))
        self.assertTrue(services.evidence.mark_verified(task.task_id))
        services.add_evidence_reference(task, "build-log")
        services.transition_task(task, TaskStatus.READY_FOR_RELEASE)
        with self.assertRaisesRegex(ValueError, "sealed at release readiness"):
            services.add_evidence_reference(task, "late-evidence")

    def test_stale_task_object_is_rejected(self):
        services = RuntimeServices()
        task = TaskRecord(task_id="stale", owner="owner", objective="stale write")
        services.create_task(task)
        old = services.load_task(task.task_id)
        services.transition_task(task, TaskStatus.GROUNDED)
        with self.assertRaisesRegex(RuntimeError, "Stale or mismatched"):
            services.transition_task(old, TaskStatus.GROUNDED)

    def test_tampered_row_is_not_audited_state(self):
        with tempfile.TemporaryDirectory() as directory:
            services = RuntimeServices(db_path=str(Path(directory) / "state.sqlite3"))
            task = TaskRecord(task_id="tamper", owner="owner", objective="audit state")
            services.create_task(task)
            services.transition_task(task, TaskStatus.GROUNDED)
            with services.store.transaction() as connection:
                row = connection.execute("SELECT payload_json FROM tasks WHERE task_id='tamper'").fetchone()
                payload = json.loads(row["payload_json"])
                payload["status"] = TaskStatus.AWAITING_APPROVAL.value
                connection.execute(
                    "UPDATE tasks SET payload_json=? WHERE task_id='tamper'",
                    (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
                )
            self.assertFalse(services.store.verify_task_status(task.task_id, "AWAITING_APPROVAL"))


if __name__ == "__main__":
    unittest.main()
