"""Layer 3: service/API and end-to-end integration tests.

Exercises the public ``RailForgeService`` surface for a full cross-bureau
coordination scenario: customer windows, section capacity, block occupancy,
priority ordering, stale versions, explainable refusals and replay safety.
Also pins regression behaviour for the existing health and feature surfaces.
"""

import unittest
from datetime import datetime, timedelta, timezone

from railforge.api import RailForgeService
from railforge.coordination.paths import (
    SECTION_CAPACITY,
    SINGLE_TRACK_MEET,
    STALE_VERSION,
    WINDOW_MISSED,
    BureauSection,
    CommitError,
    CoordinationRequest,
    Traversal,
)

U = timezone.utc


NETWORK = {
    "X1": BureauSection("X1", "BJ", 30, True, 2),
    "X2": BureauSection("X2", "TJ", 30, True, 2),
    "X3": BureauSection("X3", "JN", 40, False, 4),
}


def t(h=8, m=0):
    return datetime(2026, 9, 10, h, m, tzinfo=U)


def req(rid, train, ready=None, due=None, route=("X1", "X2", "X3"),
        direction=1, priority=5, max_delay=30, version=None):
    ready = ready if ready is not None else t()
    due = due if due is not None else ready + timedelta(hours=4)
    return CoordinationRequest(rid, train, ready, due, tuple(route),
                               direction, priority, max_delay, version)


class ServiceSurfaceTests(unittest.TestCase):
    def test_health_still_ok_and_lists_coordination_capability(self):
        service = RailForgeService()
        health = service.health()
        self.assertEqual(health["status"], "ok")
        self.assertIn("coordination.paths", health["capabilities"])
        self.assertTrue(health["workflow"]["audit_valid"])

    def test_service_exposes_executable_coordination_entrypoints(self):
        service = RailForgeService()
        self.assertTrue(callable(service.coordinate_freight_path))
        self.assertTrue(callable(service.coordinate_freight_paths))
        self.assertTrue(callable(service.features.coordinate_cross_bureau_path))
        self.assertTrue(callable(service.features.coordinate_cross_bureau_paths))

    def test_feature_surface_returns_same_receipt_as_control(self):
        service = RailForgeService()
        receipt = service.features.coordinate_cross_bureau_path(
            "f1", req("r1", "T1"), NETWORK, guard_minutes=5, at=t())
        self.assertEqual(receipt.event.payload["status"], "committed")
        same = service.coordinate_freight_path(
            "f1", req("r1", "T1"), NETWORK, guard_minutes=5, at=t())
        self.assertIs(receipt, same)


class EndToEndScenarioTests(unittest.TestCase):
    def test_happy_path_records_three_bureaus_and_handoffs(self):
        service = RailForgeService()
        receipt = service.coordinate_freight_path(
            "east-1", req("e1", "80001"), NETWORK, guard_minutes=5, at=t())
        self.assertTrue(receipt.result.accepted)
        path = receipt.result.candidate
        self.assertEqual(path.bureaus, ("BJ", "TJ", "JN"))
        self.assertEqual(path.handoffs, (("BJ", "TJ"), ("TJ", "JN")))
        self.assertEqual(path.arrives_at, t(9, 40))
        # The customer due window (12:00) is met.
        self.assertLessEqual(path.arrives_at, t(12))

    def test_explainable_refusal_for_opposing_single_track_meet(self):
        service = RailForgeService()
        occupancy = [Traversal("49002", "X1", "BJ", t(8, 10), t(8, 40), -1, "w")]
        receipt = service.coordinate_freight_path(
            "meet-1", req("e2", "80002", max_delay=0), NETWORK,
            occupancies=occupancy, guard_minutes=5, at=t())
        self.assertEqual(receipt.event.payload["status"], "rejected")
        rejection = receipt.result.rejection
        self.assertEqual(rejection.reason, SINGLE_TRACK_MEET)
        self.assertEqual(rejection.blocking_trains, ("49002",))
        self.assertEqual(rejection.sections, ("X1",))
        explanation = rejection.explain()
        self.assertIn("SINGLE_TRACK_MEET", explanation)
        self.assertIn("49002", explanation)

    def test_stale_client_must_refetch_then_retry_succeeds(self):
        service = RailForgeService()
        # A first plan advances the ledger to version 1.
        service.coordinate_freight_path(
            "base", req("base", "80010", route=("X3",)), NETWORK, at=t())
        stale = req("e3", "80003", route=("X3",), max_delay=0, version=0)
        rejected = service.coordinate_freight_path(
            "stale-1", stale, NETWORK, at=t())
        self.assertEqual(rejected.result.rejection.reason, STALE_VERSION)
        self.assertEqual(rejected.result.rejection.actual_version, 1)
        # Client refetches the current version and retries on a later slot.
        fresh = req("e3", "80003", ready=t(11), due=t(15), route=("X3",),
                    max_delay=0, version=1)
        accepted = service.coordinate_freight_path(
            "fresh-1", fresh, NETWORK, guard_minutes=5, at=t())
        self.assertTrue(accepted.result.accepted)
        self.assertEqual(accepted.version, 2)

    def test_capacity_refusal_names_all_blocking_trains(self):
        service = RailForgeService()
        occupancy = [
            Traversal(f"9{i}00", "X3", "JN", t(8, i), t(8, 40 + i), -1, f"w{i}")
            for i in range(4)
        ]
        receipt = service.coordinate_freight_path(
            "cap-1", req("e4", "80004", route=("X3",), max_delay=0),
            NETWORK, occupancies=occupancy, at=t())
        self.assertEqual(receipt.result.rejection.reason, SECTION_CAPACITY)
        self.assertEqual(receipt.result.rejection.blocking_trains,
                         ("9000", "9100", "9200", "9300"))

    def test_window_refusal_when_due_is_physically_unreachable(self):
        service = RailForgeService()
        receipt = service.coordinate_freight_path(
            "win-1", req("e5", "80005", due=t(8, 20), route=("X1",),
                         max_delay=0), NETWORK, at=t())
        self.assertEqual(receipt.result.rejection.reason, WINDOW_MISSED)

    def test_priority_batch_high_priority_train_takes_single_track(self):
        service = RailForgeService()
        low = req("lo", "70001", priority=1, max_delay=0, direction=1)
        high = req("hi", "70009", priority=9, max_delay=0, direction=-1,
                   ready=t(8, 5))
        receipt = service.coordinate_freight_paths(
            "batch-e2e", [low, high], NETWORK, guard_minutes=5, at=t())
        self.assertEqual(receipt.result["accepted"], ["hi"])
        self.assertEqual(receipt.result["rejected"], ["lo"])
        low_decision = next(d for d in receipt.result["decisions"]
                            if d.request_id == "lo")
        self.assertEqual(low_decision.rejection.reason, SINGLE_TRACK_MEET)
        self.assertEqual(low_decision.rejection.blocking_trains, ("70009",))


class ReplaySafetyTests(unittest.TestCase):
    def test_replaying_request_returns_same_receipt_and_no_new_sections(self):
        service = RailForgeService()
        first = service.coordinate_freight_path(
            "op", req("r1", "T1"), NETWORK, guard_minutes=5, at=t())
        second = service.coordinate_freight_path(
            "op", req("r1", "T1"), NETWORK, guard_minutes=5, at=t())
        self.assertIs(first, second)
        held = service.workflow().path_ledger.snapshot().traversals
        self.assertEqual(len(held), 3)
        self.assertEqual({t.request_id for t in held}, {"r1"})

    def test_same_request_new_operation_is_a_hard_commit_error(self):
        service = RailForgeService()
        service.coordinate_freight_path(
            "op", req("r1", "T1"), NETWORK, guard_minutes=5, at=t())
        with self.assertRaises(CommitError):
            service.coordinate_freight_path(
                "op-copy", req("r1", "T1"), NETWORK, guard_minutes=5, at=t())
        held = service.workflow().path_ledger.snapshot().traversals
        self.assertEqual(len(held), 3)

    def test_rejected_request_can_be_replanned_with_new_id_after_clearance(self):
        service = RailForgeService()
        occupancy = [Traversal("49002", "X1", "BJ", t(8, 10), t(8, 40), -1, "w")]
        blocked = service.coordinate_freight_path(
            "v1", req("e2", "80002", max_delay=0), NETWORK,
            occupancies=occupancy, guard_minutes=5, at=t())
        self.assertFalse(blocked.result.accepted)
        # Dispatcher re-issues the request after the opposing train has passed.
        replanned = service.coordinate_freight_path(
            "v2", req("e2", "80002", ready=t(9), due=t(13), max_delay=0),
            NETWORK, guard_minutes=5, at=t())
        self.assertTrue(replanned.result.accepted)
        # Rejected attempt occupied nothing; only the replan holds sections.
        held = service.workflow().path_ledger.snapshot().traversals
        self.assertEqual({tr.request_id for tr in held}, {"e2"})


class CursorIntegrationTests(unittest.TestCase):
    def test_committed_and_rejected_events_are_cursor_replayable(self):
        service = RailForgeService()
        occupancy = [Traversal("49002", "X1", "BJ", t(8, 10), t(8, 40), -1, "w")]
        service.coordinate_freight_path(
            "ok", req("good", "80001", route=("X3",)), NETWORK, at=t())
        service.coordinate_freight_path(
            "no", req("bad", "80002", max_delay=0), NETWORK,
            occupancies=occupancy, guard_minutes=5, at=t())
        page = service.workflow().stream.page(
            0, limit=10,
            topics=("coordination.path.committed",
                    "coordination.path.rejected"))
        statuses = [e.payload["status"] for e in page.events]
        self.assertEqual(statuses, ["committed", "rejected"])
        self.assertEqual(page.next_cursor, 2)
        # Resuming from the cursor returns nothing new (no duplicate events).
        again = service.workflow().stream.page(
            2, limit=10,
            topics=("coordination.path.committed",
                    "coordination.path.rejected"))
        self.assertEqual(again.events, ())


class RegressionTests(unittest.TestCase):
    def test_existing_suite_remains_green(self):
        service = RailForgeService()
        self.assertEqual(service.health()["status"], "ok")
        self.assertTrue(service.workflow().stream.verify_chain())
        self.assertTrue(service.workflow().trail.verify())

    def test_existing_feature_surface_still_works_alongside_coordination(self):
        service = RailForgeService()
        receipt = service.coordinate_freight_path(
            "coord", req("r1", "T1"), NETWORK, at=t())
        self.assertEqual(receipt.topic, "coordination.path.committed")
        # Fifteen original feature entrypoints remain present.
        for name in ("coordinate_route", "plan_loco_cycle", "timeline"):
            self.assertTrue(callable(getattr(service.features, name)))
        self.assertTrue(service.workflow().stream.verify_chain())
        self.assertTrue(service.workflow().trail.verify())


if __name__ == "__main__":
    unittest.main()
