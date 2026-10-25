from __future__ import annotations
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from runtime.evidence import EvidenceBundle
from runtime.services import RuntimeServices
from runtime.task_state import TaskRecord,TaskStatus

class RuntimeServicesTests(unittest.TestCase):
    def test_production_lifecycle_persists_state_and_gates_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            db=str(Path(directory)/"runtime.sqlite3")
            with patch.dict(os.environ,{"SWARM_ENV":"production","SWARM_STATE_DB":db},clear=True):
                services=RuntimeServices(db_path=db,approver_authorizer=lambda actor,r:actor==r.approver=="idp:approver",
                    evidence_authorizer=lambda actor,b:actor=="idp:reviewer" and b.task_id=="deploy-task")
                task=TaskRecord(task_id="deploy-task",owner="worker",objective="safe deploy",evidence=["build-log"],
                    approval_action="deploy",repo="demo/service",branch="release",risk_level="HIGH",
                    required_skills=["project-grounding","evidence-auditor"])
                services.create_task(task)
                for status in (TaskStatus.GROUNDED,TaskStatus.PLANNED,TaskStatus.READY,TaskStatus.IN_PROGRESS,TaskStatus.VERIFYING):
                    services.transition_task(task,status)
                services.evidence.add(EvidenceBundle(task_id=task.task_id,title="build-log",content="CI tests passed",source="ci"))
                self.assertTrue(services.evidence.mark_verified(task.task_id,verifier="idp:reviewer"))
                services.transition_task(task,TaskStatus.READY_FOR_RELEASE)
                services.approvals.request(task.task_id,"deploy","production","idp:approver",evidence=task.evidence)
                services.transition_task(task,TaskStatus.AWAITING_APPROVAL,approval_scope="production")
                self.assertFalse(services.can_perform_action(task.task_id,"deploy",scope="staging",evidence=task.evidence))
                self.assertTrue(services.approvals.approve(task.task_id,approver="idp:approver",evidence=task.evidence))
                self.assertTrue(services.can_perform_action(task.task_id,"deploy",scope="production",evidence=task.evidence))
                services.transition_task(task,TaskStatus.RELEASED,approval_scope="production")
                self.assertEqual(services.load_task(task.task_id).status,TaskStatus.RELEASED)
                self.assertTrue(services.store.verify_task_status(task.task_id,"RELEASED"))
                self.assertTrue(services.health_check().ready)

    def test_production_fails_closed_without_database_or_identity_adapters(self):
        with patch.dict(os.environ,{"SWARM_ENV":"production"},clear=True):
            with self.assertRaisesRegex(RuntimeError,"SWARM_STATE_DB"):RuntimeServices()
        with tempfile.TemporaryDirectory() as directory:
            db=str(Path(directory)/"state.sqlite3")
            with patch.dict(os.environ,{"SWARM_ENV":"production","SWARM_STATE_DB":db},clear=True):
                with self.assertRaisesRegex(RuntimeError,"approver_authorizer"):RuntimeServices(db_path=db)
                with self.assertRaisesRegex(RuntimeError,"evidence_authorizer"):
                    RuntimeServices(db_path=db,approver_authorizer=lambda actor,r:True)

    def test_stale_task_object_is_rejected(self):
        services=RuntimeServices()
        task=TaskRecord(task_id="stale",owner="owner",objective="stale write")
        services.create_task(task); old=services.load_task(task.task_id)
        services.transition_task(task,TaskStatus.GROUNDED)
        with self.assertRaisesRegex(RuntimeError,"Stale or mismatched"):services.transition_task(old,TaskStatus.GROUNDED)

    def test_tampered_row_is_not_audited_state(self):
        with tempfile.TemporaryDirectory() as directory:
            services=RuntimeServices(db_path=str(Path(directory)/"state.sqlite3"))
            task=TaskRecord(task_id="tamper",owner="owner",objective="audit state")
            services.create_task(task); services.transition_task(task,TaskStatus.GROUNDED)
            with services.store.transaction() as c:
                row=c.execute("SELECT payload_json FROM tasks WHERE task_id='tamper'").fetchone()
                p=json.loads(row["payload_json"]); p["status"]=TaskStatus.AWAITING_APPROVAL.value
                c.execute("UPDATE tasks SET payload_json=? WHERE task_id='tamper'",(json.dumps(p,sort_keys=True,separators=(",",":")),))
            self.assertFalse(services.store.verify_task_status(task.task_id,"AWAITING_APPROVAL"))

if __name__=="__main__":unittest.main()
