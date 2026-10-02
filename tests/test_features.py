import unittest
from datetime import datetime, timezone, timedelta
from railforge.api import RailForgeService
from railforge.planning.train_path_engine import Section, PathRequest
from railforge.events.cursor import FeedEvent
from railforge.eta.event_fusion import Observation

U = timezone.utc


class FeatureTests(unittest.TestCase):
    def test_all_fifteen_feature_entrypoints_exist(self):
        service = RailForgeService().features
        names = ["coordinate_route", "plan_loco_cycle", "arrange_crew_handoff", "check_route_clearance",
                 "rebalance_yard", "book_intermodal_chain", "approve_possession", "release_vehicle",
                 "reserve_capacity", "preclear_customs", "recover_disruption", "validate_hazmat_consist",
                 "reposition_wagons", "calculate_compensation", "timeline"]
        self.assertEqual(len(names), 15)
        for name in names:
            self.assertTrue(callable(getattr(service, name)))

    def test_route_and_timeline_are_published_atomically(self):
        service = RailForgeService(); at = datetime(2026,1,1,8,tzinfo=U)
        request = PathRequest("T", at, ("A",), 1, 10)
        route = service.features.coordinate_route("z01", [request], {"A": Section("A",30,True,2)}, [], 3, at)
        self.assertEqual(route.event.payload["status"], "committed")
        obs = [Observation("ops", at, at, 4, 1, 1)]
        timeline = service.features.timeline("z15", [FeedEvent("p",1,"e1",{})], obs, timedelta(hours=1), at)
        self.assertEqual(timeline.result["accepted"], [True])
        self.assertTrue(service.workflow().stream.verify_chain())
        self.assertTrue(service.workflow().trail.verify())


if __name__ == "__main__":
    unittest.main()
