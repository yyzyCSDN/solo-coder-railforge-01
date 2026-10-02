"""Layer 1: pure domain tests for cross-bureau path coordination.

No event stream, audit trail or store is involved here; these tests pin the
candidate generation, the explainable rejection codes and the versioned
ledger semantics.
"""

import unittest
from datetime import datetime, timedelta, timezone

from railforge.coordination.paths import (
    BLOCK_OCCUPIED,
    BUREAU_HANDOFF,
    DELAY_TOLERANCE,
    SECTION_CAPACITY,
    SINGLE_TRACK_MEET,
    STALE_VERSION,
    UNKNOWN_SECTION,
    WINDOW_MISSED,
    BureauSection,
    CandidatePath,
    CommitError,
    CoordinationRequest,
    PathLedger,
    Traversal,
    batch_coordinate,
    coordinate,
    generate_candidates,
)

U = timezone.utc


def sections_three_bureaus():
    return {
        "A-B": BureauSection("A-B", "BJ", 30, single_track=True, capacity_per_hour=2),
        "B-C": BureauSection("B-C", "TJ", 30, single_track=True, capacity_per_hour=2),
        "C-D": BureauSection("C-D", "JN", 40, single_track=False, capacity_per_hour=4),
    }


def at(hour=8, minute=0):
    return datetime(2026, 6, 1, hour, minute, tzinfo=U)


def request(rid="r1", train="T100", ready=None, due=None, route=("A-B", "B-C"),
            direction=1, priority=5, max_delay=30, version=None):
    ready = ready or at()
    due = due or ready + timedelta(hours=3)
    return CoordinationRequest(rid, train, ready, due, tuple(route), direction,
                               priority, max_delay, version)


class CandidateGenerationTests(unittest.TestCase):
    def test_on_time_path_spans_bureaus_and_records_handoffs(self):
        decision = coordinate(request(route=("A-B", "B-C", "C-D")),
                              sections_three_bureaus())
        self.assertTrue(decision.accepted, decision.rejection)
        path = decision.candidate
        self.assertEqual(path.delay_minutes, 0)
        self.assertEqual(path.bureaus, ("BJ", "TJ", "JN"))
        self.assertEqual(path.handoffs, (("BJ", "TJ"), ("TJ", "JN")))
        self.assertEqual([t.section for t in path.traversals],
                         ["A-B", "B-C", "C-D"])
        self.assertEqual(path.arrives_at, at(9, 40))
        self.assertEqual(path.ready_at, at(8))

    def test_shifts_departure_one_minute_at_a_time_until_clear(self):
        sections = sections_three_bureaus()
        blocker = [Traversal("T9", "A-B", "BJ", at(8, 10), at(8, 40), -1, "rx")]
        feasible, rejected = generate_candidates(
            request(rid="r2", max_delay=60), sections, blocker, guard_minutes=5)
        # Offsets 0..44 collide; 08:45 is the first clear departure.
        self.assertEqual(rejected[0].reason, SINGLE_TRACK_MEET)
        self.assertEqual(feasible[0].delay_minutes, 45)
        decision = coordinate(request(rid="r2", max_delay=60), sections,
                              blocker, guard_minutes=5)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.candidate.delay_minutes, 45)

    def test_rejects_delay_shorter_than_earliest_clear_departure(self):
        sections = sections_three_bureaus()
        blocker = [Traversal("T9", "A-B", "BJ", at(8, 10), at(8, 40), -1, "rx")]
        decision = coordinate(request(rid="r3", max_delay=20), sections,
                              blocker, guard_minutes=5)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, SINGLE_TRACK_MEET)
        self.assertIn("single track", decision.rejection.explain())

    def test_customer_window_violation_is_reported_when_due_cannot_be_met(self):
        sections = sections_three_bureaus()
        # 30 minute run, due 20 minutes after ready: even leaving on time fails.
        decision = coordinate(request(rid="r4", due=at(8, 20), route=("A-B",),
                                      max_delay=0), sections)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, WINDOW_MISSED)
        self.assertEqual(decision.rejection.sections, ("A-B",))

    def test_shifts_that_break_the_window_are_marked_but_feasible_wins(self):
        sections = sections_three_bureaus()
        # On-time departure arrives 09:40; window ends 09:00 -> rejected at the
        # on-time departure, so WINDOW_MISSED is the answer even with slack.
        decision = coordinate(request(rid="r4b", due=at(9), route=("A-B", "B-C", "C-D"),
                                      max_delay=10), sections)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, WINDOW_MISSED)


class SingleTrackMeetTests(unittest.TestCase):
    def setUp(self):
        self.sections = sections_three_bureaus()
        self.meet = [Traversal("T9", "A-B", "BJ", at(8, 10), at(8, 40), -1, "rx")]

    def test_hard_overlap_opposing_is_single_track_meet(self):
        decision = coordinate(request(rid="m1", max_delay=0), self.sections,
                              self.meet)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, SINGLE_TRACK_MEET)
        self.assertEqual(decision.rejection.blocking_trains, ("T9",))
        self.assertEqual(decision.rejection.sections, ("A-B",))

    def test_guard_only_opposing_gap_is_delay_tolerance_not_meet(self):
        # T9 vacates at 07:58; with a 5-minute guard it still blocks the 08:00
        # slot, but there is no physical meet.
        near = [Traversal("T9", "A-B", "BJ", at(7, 30), at(7, 58), -1, "rx")]
        decision = coordinate(request(rid="m2", max_delay=0), self.sections,
                              near, guard_minutes=5)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, DELAY_TOLERANCE)
        self.assertEqual(decision.rejection.blocking_trains, ("T9",))

    def test_same_direction_follower_uses_headway_guard(self):
        follower = [Traversal("T8", "A-B", "BJ", at(8, 2), at(8, 32), 1, "rx")]
        decision = coordinate(request(rid="m3", max_delay=0), self.sections,
                              follower, guard_minutes=5)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, DELAY_TOLERANCE)
        self.assertEqual(decision.rejection.blocking_trains, ("T8",))

    def test_double_track_opposing_trains_both_run(self):
        opposing = [Traversal("T9", "C-D", "JN", at(8), at(8, 40), -1, "rx")]
        decision = coordinate(request(rid="m4", route=("C-D",), direction=1,
                                      max_delay=0), self.sections, opposing,
                              guard_minutes=5)
        self.assertTrue(decision.accepted, decision.rejection)


class SectionCapacityTests(unittest.TestCase):
    def test_hour_full_is_rejected_with_section_capacity(self):
        sections = sections_three_bureaus()
        # Capacity of C-D is 4; four trains enter in the same hour as ours.
        occupancies = [
            Traversal(f"T{i}", "C-D", "JN", at(8, i), at(8, 40 + i), -1, f"rx{i}")
            for i in range(4)
        ]
        decision = coordinate(request(rid="cap1", route=("C-D",), max_delay=0),
                              sections, occupancies, guard_minutes=0)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, SECTION_CAPACITY)
        self.assertEqual(decision.rejection.sections, ("C-D",))
        self.assertEqual(decision.rejection.blocking_trains,
                         ("T0", "T1", "T2", "T3"))

    def test_entries_in_a_later_hour_do_not_count(self):
        sections = sections_three_bureaus()
        occupancies = [
            Traversal(f"T{i}", "C-D", "JN", at(9, i), at(9, 40 + i), 1, f"rx{i}")
            for i in range(4)
        ]
        decision = coordinate(request(rid="cap2", route=("C-D",), max_delay=0),
                              sections, occupancies)
        self.assertTrue(decision.accepted)


class ReferenceValidationTests(unittest.TestCase):
    def test_unknown_section_is_explainable(self):
        decision = coordinate(request(rid="u1", route=("A-B", "X-Y")),
                              sections_three_bureaus())
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection.reason, UNKNOWN_SECTION)
        self.assertEqual(decision.rejection.sections, ("X-Y",))

    def test_invalid_section_definition_is_rejected(self):
        with self.assertRaises(ValueError):
            BureauSection("bad", "BJ", 0, True, 2)
        with self.assertRaises(ValueError):
            BureauSection("bad", "BJ", 10, True, 0)

    def test_window_ordering_is_validated(self):
        with self.assertRaises(ValueError):
            coordinate(CoordinationRequest("bad", "T", at(9), at(8), ("A-B",)),
                       sections_three_bureaus())


class LedgerTests(unittest.TestCase):
    def test_add_bumps_version_and_records_sections(self):
        ledger = PathLedger()
        self.assertEqual(ledger.version, 0)
        decision = coordinate(request(rid="L1", route=("A-B", "B-C")),
                              sections_three_bureaus(), ledger=ledger)
        version = ledger.add(decision.candidate)
        self.assertEqual(version, 1)
        self.assertEqual(ledger.version, 1)
        self.assertEqual(len(ledger.snapshot().traversals), 2)
        self.assertTrue(ledger.contains_request("L1"))

    def test_replaying_same_request_cannot_occupy_twice(self):
        ledger = PathLedger()
        decision = coordinate(request(rid="L2"), sections_three_bureaus(),
                              ledger=ledger)
        ledger.add(decision.candidate)
        with self.assertRaises(CommitError):
            ledger.add(decision.candidate)
        self.assertEqual(len(ledger.snapshot().traversals),
                         len(decision.candidate.traversals))
        self.assertEqual(ledger.version, 1)

    def test_stale_expected_version_is_rejected_at_commit(self):
        ledger = PathLedger()
        decision = coordinate(request(rid="L3"), sections_three_bureaus(),
                              ledger=ledger)
        ledger.add(decision.candidate)
        other = coordinate(request(rid="L4"), sections_three_bureaus(),
                           ledger=ledger).candidate
        with self.assertRaises(CommitError):
            ledger.add(other, expected_version=0)

    def test_snapshot_restore_rolls_back_a_pending_add(self):
        ledger = PathLedger()
        decision = coordinate(request(rid="L5"), sections_three_bureaus(),
                              ledger=ledger)
        checkpoint = ledger.snapshot()
        ledger.add(decision.candidate)
        self.assertEqual(ledger.version, 1)
        ledger.restore(checkpoint)
        self.assertEqual(ledger.version, 0)
        self.assertEqual(ledger.snapshot().traversals, ())
        self.assertFalse(ledger.contains_request("L5"))

    def test_stale_request_is_refused_before_section_examination(self):
        ledger = PathLedger()
        decision = coordinate(request(rid="L6"), sections_three_bureaus(),
                              ledger=ledger)
        ledger.add(decision.candidate)
        stale = coordinate(request(rid="L7", version=0), sections_three_bureaus(),
                           ledger=ledger, ledger_version=0)
        self.assertFalse(stale.accepted)
        self.assertEqual(stale.rejection.reason, STALE_VERSION)
        self.assertEqual(stale.rejection.expected_version, 0)
        self.assertEqual(stale.rejection.actual_version, 1)


class BatchPriorityTests(unittest.TestCase):
    def test_higher_priority_wins_single_track_meet(self):
        sections = sections_three_bureaus()
        # Eastbound low priority at 08:00 vs westbound high priority 08:05.
        low = request("lo", "LO", priority=1, max_delay=0, direction=1)
        high = request("hi", "HI", priority=9, max_delay=0, direction=-1,
                       ready=at(8, 5))
        decisions = batch_coordinate([low, high], sections)
        order = {d.request_id: d for d in decisions}
        self.assertTrue(order["hi"].accepted)
        self.assertFalse(order["lo"].accepted)
        self.assertEqual(order["lo"].rejection.reason, SINGLE_TRACK_MEET)
        self.assertEqual(order["lo"].rejection.blocking_trains, ("HI",))

    def test_batch_result_order_matches_input_order(self):
        sections = sections_three_bureaus()
        first = request("first", "F1", route=("C-D",), priority=1)
        second = request("second", "F2", route=("C-D",), priority=2,
                         ready=at(8, 30))
        decisions = batch_coordinate([first, second], sections, guard_minutes=5)
        self.assertEqual([d.request_id for d in decisions], ["first", "second"])

    def test_accepted_plans_block_later_requests_in_same_batch(self):
        sections = sections_three_bureaus()
        a = request("a", "A", route=("A-B",), priority=5, max_delay=0)
        b = request("b", "B", route=("A-B",), priority=4, max_delay=0,
                    ready=at(8, 2))
        decisions = batch_coordinate([a, b], sections, guard_minutes=5)
        by_id = {d.request_id: d for d in decisions}
        self.assertTrue(by_id["a"].accepted)
        self.assertFalse(by_id["b"].accepted)
        self.assertEqual(by_id["b"].rejection.blocking_trains, ("A",))


if __name__ == "__main__":
    unittest.main()
