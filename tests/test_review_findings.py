"""Regression tests for defects found by an independent review of the hardening pass."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from runtime import cli
from runtime.approval import ApprovalGate, _canonical_action
from runtime.evidence import EvidenceBundle
from runtime.locks import LockRegistry
from runtime.repo_grounding import RepoGroundingEngine
from runtime.services import RuntimeServices
from runtime.task_state import TaskRecord, TaskStatus
from runtime.validation import run_full_validation

AUDIT_KEY = "test-audit-key-0123456789abcdef0123"


def _run_cli(*argv: str) -> tuple[int, object]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(list(argv))
    return code, json.loads(buffer.getvalue())


class InflectedCompoundActionTests(unittest.TestCase):
    def test_inflected_risk_words_still_form_compounds(self) -> None:
        cases = {
            "deploy and run migrations": "compound:deploy+migration",
            "deploy and rotate secrets": "compound:deploy+secret-rotation",
            "merge, then publishing docs": "compound:merge+publish",
            "deploying after dropping tables": "compound:deploy+destructive-action",
            "deletes old releases": "compound:destructive-action+release",
            "merged and deployed": "compound:deploy+merge",
        }
        for action, expected in cases.items():
            with self.subTest(action=action):
                self.assertEqual(_canonical_action(action), expected)

    def test_single_inflected_category_still_matches_its_approval(self) -> None:
        self.assertEqual(_canonical_action("run migrations"), "migration")
        self.assertEqual(_canonical_action("deploying"), "deploy")

    def test_approved_deploy_does_not_cover_deploy_plus_migrations(self) -> None:
        gate = ApprovalGate()
        gate.request("t", "deploy", "prod", "approver", evidence=["e"])
        gate.approve("t", approver="approver", evidence=["e"])
        self.assertFalse(gate.can_proceed("t", "deploy and run migrations", evidence=["e"], scope="prod"))
        self.assertFalse(gate.can_proceed("t", "deploy and rotate secrets", evidence=["e"], scope="prod"))


class ProductionSeparationOfDutiesTests(unittest.TestCase):
    def _ready_task(self, services: RuntimeServices) -> TaskRecord:
        task = TaskRecord(task_id="t", owner="agent:worker", objective="x", approval_action="deploy")
        services.create_task(task)
        for status in (TaskStatus.GROUNDED, TaskStatus.PLANNED, TaskStatus.READY,
                       TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING):
            services.transition_task(task, status)
        services.add_evidence_reference(task, "log")
        services.evidence.add(EvidenceBundle(task_id="t", title="log", content="ok"))
        services.evidence.mark_verified("t", verifier="idp:reviewer")
        services.transition_task(task, TaskStatus.READY_FOR_RELEASE)
        return task

    def test_owner_cannot_self_approve_with_a_forged_requester(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "s.db")
            env = {"SWARM_ENV": "production", "SWARM_STATE_DB": db, "SWARM_AUDIT_KEY": AUDIT_KEY}
            with patch.dict(os.environ, env, clear=True):
                services = RuntimeServices(
                    db_path=db, approver_authorizer=lambda actor, record: actor == record.approver,
                    evidence_authorizer=lambda actor, bundle: actor == "idp:reviewer",
                )
                task = self._ready_task(services)
                for approver, requester in (("agent:worker", "nobody"), ("Agent:Worker", "agent:worker")):
                    with self.subTest(approver=approver, requester=requester):
                        try:
                            services.approvals.request("t", "deploy", "production", approver,
                                                       evidence=list(task.evidence), requester=requester)
                        except ValueError:
                            continue
                        if task.status != TaskStatus.AWAITING_APPROVAL:
                            services.transition_task(task, TaskStatus.AWAITING_APPROVAL, approval_scope="production")
                        services.approvals.approve("t", approver=approver, evidence=list(task.evidence))
                        self.assertFalse(
                            services.can_perform_action("t", "deploy", scope="production", evidence=task.evidence)
                        )


class ProductionRawTaskWriteTests(unittest.TestCase):
    def test_put_task_json_is_refused_in_production(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "s.db")
            env = {"SWARM_ENV": "production", "SWARM_STATE_DB": db, "SWARM_AUDIT_KEY": AUDIT_KEY}
            with patch.dict(os.environ, env, clear=True):
                services = RuntimeServices(
                    db_path=db, approver_authorizer=lambda actor, record: True,
                    evidence_authorizer=lambda actor, bundle: True,
                )
                with self.assertRaisesRegex(RuntimeError, "RuntimeServices"):
                    services.store.put_task_json("t", "{}", "now")

    def test_replay_rejects_resume_past_the_blocked_stage(self) -> None:
        services = RuntimeServices()
        task = TaskRecord(task_id="t", owner="o", objective="x")
        services.create_task(task)
        services.add_blocker(task, "dep")
        # Development allows the raw write; the audit replay must still catch the skipped stages.
        payload = json.loads(services.store.get_task_json("t"))
        payload["blocked_from"] = "IN_PROGRESS"
        services.store.put_task_json("t", json.dumps(payload, sort_keys=True, separators=(",", ":")), payload["updated_at"])
        task = services.load_task("t")
        services.transition_task(task, TaskStatus.IN_PROGRESS, justification="forged")
        self.assertFalse(services.store.verify_task_status("t", "IN_PROGRESS"))


class SelftestIsolationTests(unittest.TestCase):
    def test_selftest_leaves_the_configured_database_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "user.db")
            with patch.dict(os.environ, {"SWARM_STATE_DB": db}):
                results = run_full_validation()
            self.assertTrue(all(result.passed for result in results))
            self.assertFalse(Path(db).exists())

    def test_selftest_passes_when_production_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = {"SWARM_ENV": "production", "SWARM_STATE_DB": str(Path(directory) / "p.db"),
                   "SWARM_AUDIT_KEY": AUDIT_KEY}
            with patch.dict(os.environ, env):
                failures = [r.name for r in run_full_validation() if not r.passed]
            self.assertEqual(failures, [])


class GroundingBoundaryTests(unittest.TestCase):
    def test_snake_case_names_and_env_variants_are_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "settings.py").write_text("db_password = 1\ndef authenticate_user(): pass\n", encoding="utf-8")
            Path(directory, ".env.production").write_text("JWT_SECRET=x\n", encoding="utf-8")
            risks = RepoGroundingEngine(directory)._detect_risks()
            self.assertIn("Potential risk area: secret", risks)
            self.assertIn("Potential risk area: auth", risks)
            self.assertIn("Potential risk area: token", risks)
            self.assertIn("Configuration and environment exposure risk", risks)


class CliTests(unittest.TestCase):
    def test_verify_accepts_a_multi_line_checkpoint_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db, out = str(Path(directory) / "s.db"), str(Path(directory) / "anchors.jsonl")
            with patch.dict(os.environ, {}, clear=True):
                _run_cli("--db", db, "task", "create", "t", "--owner", "o", "--objective", "x")
                _run_cli("--db", db, "audit", "checkpoint", "--out", out)
                _run_cli("--db", db, "task", "move", "t", "GROUNDED")
                _run_cli("--db", db, "audit", "checkpoint", "--out", out)
                code, result = _run_cli("--db", db, "audit", "verify", "--anchor", out)
            self.assertEqual(code, 0)
            self.assertTrue(result["valid"])

    def test_approval_check_reports_the_latest_denial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "s.db")
            with patch.dict(os.environ, {}, clear=True):
                _run_cli("--db", db, "task", "create", "t", "--owner", "o", "--objective", "x", "--action", "deploy")
                services = RuntimeServices(db_path=db)
                for index in range(3):
                    services.store.append_event("action.denied", task_id="t", payload={"reason": f"old-{index}"})
                code, result = _run_cli("--db", db, "approval", "check", "t", "--scope", "prod")
            self.assertFalse(result["allowed"])
            self.assertEqual(result["denial_reason"], "approval_request_missing")

    def test_lock_list_shows_each_lock_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "s.db")
            with patch.dict(os.environ, {}, clear=True):
                registry = LockRegistry(db_path=db)
                registry.reserve("src", "t", "o", "dir")
                registry.reserve("src/a.py", "t", "o", "file")
                code, result = _run_cli("--db", db, "lock", "list")
            self.assertEqual(sorted(lock["resource"] for lock in result), ["src", "src/a.py"])


if __name__ == "__main__":
    unittest.main()
