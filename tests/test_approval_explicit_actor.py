from __future__ import annotations

import unittest

from runtime.approval import ApprovalGate, ApprovalStatus


class ExplicitApprovalActorTests(unittest.TestCase):
    def test_missing_approver_or_evidence_does_not_approve(self) -> None:
        gate = ApprovalGate()
        evidence = ["review log"]
        gate.request("task-explicit", "deploy", "production", "release-manager", evidence=evidence)

        self.assertFalse(gate.approve("task-explicit"))
        self.assertFalse(gate.approve("task-explicit", approver="release-manager"))
        self.assertEqual(gate.get("task-explicit").status, ApprovalStatus.PENDING)

        self.assertTrue(
            gate.approve(
                "task-explicit",
                approver="release-manager",
                evidence=evidence,
            )
        )
        self.assertEqual(gate.get("task-explicit").status, ApprovalStatus.APPROVED)


if __name__ == "__main__":
    unittest.main()
