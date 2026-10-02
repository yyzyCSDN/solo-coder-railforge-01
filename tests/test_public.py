import unittest
from datetime import datetime, timezone, timedelta
from railforge.api import RailForgeService
from railforge.signaling.block_occupancy import Occupancy
from railforge.consist.integrity import WagonLink
from railforge.braking.brake_percentage import Vehicle
from railforge.routing.clearance import Segment, TrainProfile

U = timezone.utc


class PublicTests(unittest.TestCase):
    def test_health_exposes_workflow_plane(self):
        health = RailForgeService().health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["runtime_dependencies"], 0)
        self.assertGreaterEqual(len(health["capabilities"]), 20)
        self.assertTrue(health["workflow"]["audit_valid"])

    def test_domain_smoke(self):
        service = RailForgeService()
        a = Occupancy("A", "B1", datetime(2026, 1, 1, 8, tzinfo=U), datetime(2026, 1, 1, 9, tzinfo=U), 1)
        b = Occupancy("B", "B1", datetime(2026, 1, 1, 10, tzinfo=U), datetime(2026, 1, 1, 11, tzinfo=U), 1)
        self.assertEqual(service.block_conflicts(b, [a], timedelta(minutes=5)), [])
        self.assertEqual(service.validate_consist([
            WagonLink(1, "W1", None, "W2", True), WagonLink(2, "W2", "W1", None, True)
        ]), ("W1", "W2"))
        self.assertGreater(service.brake_percentage([Vehicle("W", 100, 90)], 0), 80)
        self.assertTrue(service.route_clearance(TrainProfile(3.0, 2.5, 100, 20), [
            Segment("S", 4, 3, 120, 25)
        ]))

    def test_atomic_workflow_smoke(self):
        service = RailForgeService()
        at = datetime(2026, 1, 1, 8, tzinfo=U)
        candidate = Occupancy("T1", "B1", at, at + timedelta(hours=1), 1)
        receipt = service.workflow().reserve_block("op-public", candidate, [], timedelta(minutes=5), at)
        self.assertEqual(receipt.event.payload["status"], "committed")
        self.assertEqual(receipt.event.payload["control_path"], "atomic")
        self.assertTrue(service.workflow().stream.verify_chain())
        self.assertTrue(service.workflow().trail.verify())
        self.assertIs(receipt, service.workflow().reserve_block("op-public", candidate, [], timedelta(minutes=5), at))


if __name__ == "__main__":
    unittest.main()
