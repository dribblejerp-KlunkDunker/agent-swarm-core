from __future__ import annotations

import unittest

from runtime.evidence import EvidenceBundle, EvidenceRegistry, EvidenceStatus


class EvidenceRegistryHardeningTests(unittest.TestCase):
    def test_evidence_cannot_be_inserted_as_already_verified(self) -> None:
        registry = EvidenceRegistry()
        bundle = EvidenceBundle(
            task_id="task-forged",
            title="claimed verification",
            content="not yet reviewed",
            status=EvidenceStatus.VERIFIED,
        )
        with self.assertRaisesRegex(ValueError, "must start as PENDING"):
            registry.add(bundle)
        self.assertFalse(registry.has_evidence("task-forged"))

    def test_empty_evidence_content_is_rejected(self) -> None:
        registry = EvidenceRegistry()
        with self.assertRaisesRegex(ValueError, "non-empty content"):
            registry.add(EvidenceBundle(task_id="task-empty", title="empty", content="  "))


if __name__ == "__main__":
    unittest.main()
