import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from railforge.api import RailForgeService
from railforge.planning.cross_bureau_paths import (
    CAPACITY_EXCEEDED,
    SINGLE_TRACK_MEET,
    STALE_VERSION,
    WINDOW_INFEASIBLE,
    CandidatePath,
    CorridorSection,
    CorridorState,
    Occupancy,
    PathRequest,
    Rejection,
    evaluate,
    explain_rejection,
    generate_candidates,
    plan_batch,
)
from railforge.workflows.control import RailForgeWorkflowControl

U = timezone.utc


def at(hour, minute=0):
    return datetime(2026, 3, 1, hour, minute, tzinfo=U)


def corridor_sections():
    return {
        "N1": CorridorSection("N1", "North", 30, True, 4),
        "S1": CorridorSection("S1", "South", 20, False, 2),
    }


class DomainTests(unittest.TestCase):
    def test_candidates_respect_window_capacity_and_bureau_dwell(self):
        req = PathRequest("r1", "T1", at(8), at(10), ("N1", "S1"), 5, 1, dwell_minutes=10)
        candidates = generate_candidates(req, corridor_sections(), [], 5, limit=2,
                                         step_minutes=15)
        self.assertEqual(len(candidates), 2)
        first, second = candidates
        # Cross-bureau dwell of 10 minutes is inserted at the North/South boundary.
        self.assertEqual(first.departure, at(8))
        self.assertEqual(first.slots[0].section, "N1")
        self.assertEqual(first.slots[0].bureau, "North")
        self.assertEqual((first.slots[0].start, first.slots[0].end), (at(8), at(8, 30)))
        self.assertEqual(first.slots[1].section, "S1")
        self.assertEqual(first.slots[1].bureau, "South")
        self.assertEqual((first.slots[1].start, first.slots[1].end), (at(8, 40), at(9)))
        self.assertEqual(first.arrival, at(9))
        self.assertEqual(first.delay_minutes, 0)
        self.assertEqual(second.departure, at(8, 15))
        for candidate in candidates:
            self.assertLessEqual(candidate.arrival, at(10))

    def test_block_occupancy_defers_candidate(self):
        occupied = [Occupancy("X", "N1", at(8), at(8, 40), 1)]
        req = PathRequest("r1", "T1", at(8), at(10), ("N1",), 5, 1)
        best = evaluate(req, corridor_sections(), occupied, 5)
        self.assertIsInstance(best, CandidatePath)
        # Same-direction follow on a single-track section waits out the occupancy
        # plus the 5 minute headway guard.
        self.assertEqual(best.departure, at(8, 45))
        self.assertEqual(best.delay_minutes, 45)

    def test_single_track_meet_rejection_is_explainable(self):
        occupied = [Occupancy("X", "N1", at(8), at(8, 40), -1)]
        req = PathRequest("r2", "T2", at(8), at(8, 35), ("N1",), 5, 1)
        outcome = evaluate(req, corridor_sections(), occupied, 5)
        self.assertIsInstance(outcome, Rejection)
        self.assertEqual(outcome.reason, SINGLE_TRACK_MEET)
        self.assertEqual(outcome.section, "N1")
        self.assertEqual(outcome.conflicting_trains, ("X",))
        self.assertIn("single-track", outcome.detail)
        self.assertIn("X", outcome.detail)

    def test_capacity_exceeded_rejection_is_explainable(self):
        # Two opposing trains saturate the 2/hour capacity of the double-track
        # section without ever conflicting on the running line.
        occupied = [
            Occupancy("X1", "S1", at(8), at(8, 20), -1),
            Occupancy("X2", "S1", at(8, 10), at(8, 30), -1),
        ]
        req = PathRequest("r3", "T3", at(8), at(8, 25), ("S1",), 5, 1)
        outcome = evaluate(req, corridor_sections(), occupied, 5)
        self.assertIsInstance(outcome, Rejection)
        self.assertEqual(outcome.reason, CAPACITY_EXCEEDED)
        self.assertEqual(outcome.section, "S1")
        self.assertIn("capacity", outcome.detail)

    def test_window_infeasible_rejection_is_explainable(self):
        req = PathRequest("r4", "T4", at(8), at(8, 20), ("N1",), 5, 1)
        outcome = evaluate(req, corridor_sections(), [], 5)
        self.assertIsInstance(outcome, Rejection)
        self.assertEqual(outcome.reason, WINDOW_INFEASIBLE)
        self.assertIn("window", outcome.detail)

    def test_priority_orders_batch_planning(self):
        sections = {"N1": CorridorSection("N1", "North", 60, True, 4)}
        low = PathRequest("low", "TL", at(8), at(12), ("N1",), 1, 1)
        high = PathRequest("high", "TH", at(8), at(12), ("N1",), 9, 1)
        accepted, rejected = plan_batch([low, high], sections, [], 5)
        self.assertEqual(rejected, [])
        # Higher priority is planned first and takes the 08:00 departure; the
        # lower-priority train is deferred behind it plus headway.
        self.assertEqual(accepted["high"].departure, at(8))
        self.assertEqual(accepted["low"].departure, at(9, 5))

    def test_invalid_inputs_raise_before_any_planning(self):
        req = PathRequest("r5", "T5", at(8), at(9), ("N1",), 5, 1)
        with self.assertRaises(ValueError):
            generate_candidates(req, corridor_sections(), [], -1)
        with self.assertRaises(KeyError):
            generate_candidates(
                PathRequest("r6", "T6", at(8), at(9), ("ZZ",), 5, 1),
                corridor_sections(), [], 5)
        with self.assertRaises(ValueError):
            generate_candidates(
                PathRequest("r7", "T7", at(9), at(8), ("N1",), 5, 1),
                corridor_sections(), [], 5)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.control = RailForgeWorkflowControl()
        self.sections = corridor_sections()
        self.key = "cross-bureau-corridor:corridor-1"

    def request(self, request_id="r1", train="T1", expected_version=0):
        return PathRequest(request_id, train, at(8), at(10), ("N1", "S1"), 5, 1,
                           expected_version=expected_version)

    def test_commit_is_atomic_and_writes_plan_event_and_audit(self):
        receipt = self.control.commit_cross_bureau_path(
            "op1", "corridor-1", self.request(), self.sections, [], 5, at(7, 55))
        self.assertEqual(receipt.event.payload["status"], "committed")
        self.assertEqual(receipt.event.payload["control_path"], "atomic")
        self.assertEqual(receipt.event.payload["decision"], "accepted")
        self.assertEqual(receipt.result.decision, "accepted")
        self.assertEqual(receipt.result.candidate.arrival, at(8, 50))
        # Plan, cursor event and audit record all landed exactly once.
        state = self.control.store.read(self.key)
        self.assertEqual(state.version, 1)
        self.assertEqual(len(state.value.slots), 2)
        self.assertEqual(self.control.stream.head, 1)
        self.assertTrue(self.control.stream.verify_chain())
        self.assertEqual(len(self.control.trail), 1)
        self.assertTrue(self.control.trail.verify())

    def test_replay_same_operation_does_not_reoccupy(self):
        first = self.control.commit_cross_bureau_path(
            "op1", "corridor-1", self.request(), self.sections, [], 5, at(7, 55))
        second = self.control.commit_cross_bureau_path(
            "op1", "corridor-1", self.request(), self.sections, [], 5, at(7, 55))
        self.assertIs(first, second)
        self.assertEqual(len(self.control.store.read(self.key).value.slots), 2)
        self.assertEqual(self.control.stream.head, 1)
        self.assertEqual(len(self.control.trail), 1)

    def test_replay_same_request_id_does_not_reoccupy(self):
        first = self.control.commit_cross_bureau_path(
            "op1", "corridor-1", self.request("r1"), self.sections, [], 5, at(7, 55))
        # Same business request replayed under a fresh operation id.
        replay = self.control.commit_cross_bureau_path(
            "op2", "corridor-1", self.request("r1"), self.sections, [], 5, at(7, 56))
        self.assertIs(first, replay)
        self.assertEqual(len(self.control.store.read(self.key).value.slots), 2)
        self.assertEqual(self.control.stream.head, 1)
        self.assertEqual(len(self.control.trail), 1)

    def test_stale_version_is_an_explainable_rejection(self):
        self.control.commit_cross_bureau_path(
            "op1", "corridor-1", self.request("r1", "T1", expected_version=0),
            self.sections, [], 5, at(7, 55))
        # A peer bureau commits against the same corridor, moving it to version 1.
        stale = self.control.commit_cross_bureau_path(
            "op2", "corridor-1", self.request("r2", "T2", expected_version=0),
            self.sections, [], 5, at(7, 56))
        self.assertEqual(stale.result.decision, "rejected")
        self.assertEqual(stale.result.rejection.reason, STALE_VERSION)
        self.assertIn("expected 0", stale.result.rejection.detail)
        self.assertIn("current 1", stale.result.rejection.detail)
        # The rejection is observable but never touches the corridor plan.
        self.assertEqual(self.control.store.read(self.key).version, 1)
        self.assertEqual(len(self.control.store.read(self.key).value.slots), 2)
        self.assertEqual(self.control.stream.head, 2)
        self.assertEqual(len(self.control.trail), 2)
        self.assertTrue(self.control.stream.verify_chain())
        self.assertTrue(self.control.trail.verify())

    def test_meet_rejection_is_committed_without_occupying(self):
        occupied = [Occupancy("X", "N1", at(8), at(9, 30), -1)]
        req = PathRequest("r9", "T9", at(8), at(8, 35), ("N1",), 5, 1,
                          expected_version=0)
        receipt = self.control.commit_cross_bureau_path(
            "op9", "corridor-1", req, self.sections, occupied, 5, at(7, 55))
        self.assertEqual(receipt.result.decision, "rejected")
        self.assertEqual(receipt.result.rejection.reason, SINGLE_TRACK_MEET)
        # No corridor state is created for a rejection.
        self.assertIsNone(self.control.store.read(self.key))
        self.assertEqual(self.control.stream.head, 1)
        self.assertEqual(len(self.control.trail), 1)

    def test_rollback_when_event_publish_fails(self):
        req = self.request()
        with patch.object(self.control.stream, "publish",
                          side_effect=RuntimeError("stream down")):
            with self.assertRaises(RuntimeError):
                self.control.commit_cross_bureau_path(
                    "op1", "corridor-1", req, self.sections, [], 5, at(7, 55))
        # The corridor plan write was rolled back and nothing else was recorded.
        self.assertIsNone(self.control.store.read(self.key))
        self.assertEqual(self.control.stream.head, 0)
        self.assertEqual(len(self.control.trail), 0)
        self.assertNotIn("op1", self.control.receipts)
        # The operation can be retried cleanly once the stream recovers.
        receipt = self.control.commit_cross_bureau_path(
            "op1", "corridor-1", req, self.sections, [], 5, at(7, 55))
        self.assertEqual(receipt.result.decision, "accepted")
        self.assertEqual(self.control.store.read(self.key).version, 1)

    def test_rollback_when_audit_fails_retracts_event_and_plan(self):
        req = self.request()
        with patch.object(self.control.trail, "append",
                          side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                self.control.commit_cross_bureau_path(
                    "op1", "corridor-1", req, self.sections, [], 5, at(7, 55))
        self.assertIsNone(self.control.store.read(self.key))
        self.assertEqual(self.control.stream.head, 0)
        self.assertTrue(self.control.stream.verify_chain())
        self.assertEqual(len(self.control.trail), 0)
        self.assertNotIn("op1", self.control.receipts)

    def test_invalid_request_leaves_no_trace(self):
        bad = PathRequest("rX", "TX", at(8), at(9), ("ZZ",), 5, 1)
        with self.assertRaises(KeyError):
            self.control.commit_cross_bureau_path(
                "opX", "corridor-1", bad, self.sections, [], 5, at(7, 55))
        self.assertIsNone(self.control.store.read(self.key))
        self.assertEqual(self.control.stream.head, 0)
        self.assertEqual(len(self.control.trail), 0)

    def test_batch_commits_in_priority_order_atomically(self):
        sections = {"N1": CorridorSection("N1", "North", 60, True, 4)}
        low = PathRequest("low", "TL", at(8), at(12), ("N1",), 1, 1)
        high = PathRequest("high", "TH", at(8), at(12), ("N1",), 9, 1)
        receipts = self.control.commit_cross_bureau_batch(
            "batch", "corridor-1", [low, high], sections, [], 5, at(7, 55))
        self.assertEqual(receipts["high"].result.candidate.departure, at(8))
        self.assertEqual(receipts["low"].result.candidate.departure, at(9, 5))
        key = "cross-bureau-corridor:corridor-1"
        self.assertEqual(len(self.control.store.read(key).value.slots), 2)
        self.assertTrue(self.control.stream.verify_chain())
        self.assertTrue(self.control.trail.verify())


class ApiTests(unittest.TestCase):
    def test_health_lists_cross_bureau_capability(self):
        service = RailForgeService()
        self.assertIn("planning.cross_bureau_paths", service.health()["capabilities"])

    def test_service_coordinates_and_replays_without_reoccupying(self):
        service = RailForgeService()
        req = PathRequest("r1", "T1", at(8), at(10), ("N1", "S1"), 5, 1,
                          expected_version=0)
        receipt = service.coordinate_cross_bureau_path(
            "op1", "corridor-1", req, corridor_sections(), [], 5, at(7, 55))
        self.assertEqual(receipt.event.payload["decision"], "accepted")
        replay = service.coordinate_cross_bureau_path(
            "op1", "corridor-1", req, corridor_sections(), [], 5, at(7, 55))
        self.assertIs(receipt, replay)
        state = service.workflow().store.read("cross-bureau-corridor:corridor-1")
        self.assertEqual(len(state.value.slots), 2)
        self.assertTrue(service.workflow().stream.verify_chain())
        self.assertTrue(service.workflow().trail.verify())

    def test_service_returns_explainable_meet_rejection(self):
        service = RailForgeService()
        occupied = [Occupancy("X", "N1", at(8), at(9, 30), -1)]
        req = PathRequest("r2", "T2", at(8), at(8, 35), ("N1",), 5, 1,
                          expected_version=0)
        receipt = service.features.coordinate_cross_bureau_path(
            "op2", "corridor-1", req, corridor_sections(), occupied, 5, at(7, 55))
        self.assertEqual(receipt.result.decision, "rejected")
        self.assertEqual(receipt.result.rejection.reason, SINGLE_TRACK_MEET)
        self.assertIn("single-track", receipt.result.rejection.detail)

    def test_service_batch_respects_priority(self):
        service = RailForgeService()
        sections = {"N1": CorridorSection("N1", "North", 60, True, 4)}
        low = PathRequest("low", "TL", at(8), at(12), ("N1",), 1, 1)
        high = PathRequest("high", "TH", at(8), at(12), ("N1",), 9, 1)
        receipts = service.coordinate_cross_bureau_batch(
            "batch", "corridor-1", [low, high], sections, [], 5, at(7, 55))
        self.assertEqual(receipts["high"].result.decision, "accepted")
        self.assertEqual(receipts["low"].result.decision, "accepted")
        self.assertLess(receipts["high"].result.candidate.departure,
                        receipts["low"].result.candidate.departure)


if __name__ == "__main__":
    unittest.main()
