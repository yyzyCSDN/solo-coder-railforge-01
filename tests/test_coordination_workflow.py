"""Layer 2: atomic control-plane tests for cross-bureau coordination.

These verify that accepting a request writes plan + cursor event + audit row
as one unit, that a failure anywhere in that unit rolls every write back, and
that replaying a request never occupies a section twice.
"""

import unittest
from datetime import datetime, timedelta, timezone
from threading import Barrier, Thread

from railforge.audit.trail import Trail
from railforge.coordination.paths import (
    SECTION_CAPACITY,
    SINGLE_TRACK_MEET,
    STALE_VERSION,
    BureauSection,
    CommitError,
    CoordinationRequest,
    Traversal,
)
from railforge.events.stream import EventStream
from railforge.workflows.control import RailForgeWorkflowControl

U = timezone.utc


def sections():
    return {
        "A-B": BureauSection("A-B", "BJ", 30, True, 2),
        "B-C": BureauSection("B-C", "TJ", 30, True, 2),
        "C-D": BureauSection("C-D", "JN", 40, False, 4),
    }


def at(h=8, m=0):
    return datetime(2026, 6, 1, h, m, tzinfo=U)


def make_request(rid="r1", train="T100", ready=None, due=None,
                 route=("A-B", "B-C"), direction=1, priority=5,
                 max_delay=30, version=0):
    ready = ready or at()
    due = due or ready + timedelta(hours=3)
    return CoordinationRequest(rid, train, ready, due, tuple(route),
                               direction, priority, max_delay, version)


class AtomicCommitTests(unittest.TestCase):
    def test_accepted_commit_writes_plan_event_audit_and_sections(self):
        control = RailForgeWorkflowControl()
        receipt = control.coordinate_path("op-1", make_request(), sections(),
                                          guard_minutes=5, at=at())
        self.assertEqual(receipt.event.payload["status"], "committed")
        self.assertEqual(receipt.event.payload["control_path"], "atomic")
        self.assertEqual(receipt.topic, "coordination.path.committed")
        # Plan row exists in the versioned store.
        stored = control.store.read("coordination.plan:r1")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.value["status"], "committed")
        # Cursor event sits on the stream, audit trail advanced.
        self.assertEqual(control.stream.head, 1)
        self.assertEqual(control.trail._rows[-1].action,
                         "coordination.path.committed")
        self.assertEqual(receipt.audit_index, 1)
        # Ledger owns exactly the two traversed sections.
        self.assertEqual(control.path_ledger.version, 1)
        held = control.path_ledger.snapshot().traversals
        self.assertEqual([t.section for t in held], ["A-B", "B-C"])
        self.assertTrue(control.stream.verify_chain())
        self.assertTrue(control.trail.verify())

    def test_rejection_writes_event_and_audit_but_no_plan_or_section(self):
        control = RailForgeWorkflowControl()
        meet = [Traversal("T9", "A-B", "BJ", at(8, 10), at(8, 40), -1, "rx")]
        receipt = control.coordinate_path("op-meet", make_request(
            rid="r2", max_delay=0), sections(), meet, guard_minutes=5, at=at())
        self.assertEqual(receipt.event.payload["status"], "rejected")
        self.assertEqual(receipt.result.rejection.reason, SINGLE_TRACK_MEET)
        self.assertIsNone(control.store.read("coordination.plan:r2"))
        self.assertEqual(control.path_ledger.version, 0)
        self.assertEqual(control.path_ledger.snapshot().traversals, ())
        # The rejection is still cursor-published and audited.
        self.assertEqual(control.stream.head, 1)
        self.assertEqual(control.trail._rows[-1].action,
                         "coordination.path.rejected")
        self.assertTrue(control.stream.verify_chain())
        self.assertTrue(control.trail.verify())

    def test_stale_version_rejected_without_state_change(self):
        control = RailForgeWorkflowControl()
        control.coordinate_path("op-1", make_request(), sections(),
                                guard_minutes=5, at=at())
        head_before = control.stream.head
        stale = make_request(rid="r-stale", train="T200", version=0)
        receipt = control.coordinate_path("op-stale", stale, sections(), at=at())
        self.assertEqual(receipt.result.rejection.reason, STALE_VERSION)
        self.assertEqual(receipt.result.rejection.actual_version, 1)
        self.assertEqual(receipt.event.payload["rejection"]["reason"],
                         STALE_VERSION)
        self.assertEqual(control.path_ledger.version, 1)
        self.assertIsNone(control.store.read("coordination.plan:r-stale"))
        self.assertEqual(control.stream.head, head_before + 1)

    def test_replay_same_operation_returns_identical_receipt(self):
        control = RailForgeWorkflowControl()
        first = control.coordinate_path("op-1", make_request(), sections(),
                                        guard_minutes=5, at=at())
        second = control.coordinate_path("op-1", make_request(), sections(),
                                         guard_minutes=5, at=at())
        self.assertIs(first, second)
        self.assertEqual(control.path_ledger.version, 1)
        self.assertEqual(len(control.path_ledger.snapshot().traversals), 2)
        self.assertEqual(control.stream.head, 1)
        self.assertEqual(len(control.trail._rows), 1)

    def test_replayed_request_under_new_operation_cannot_double_occupy(self):
        control = RailForgeWorkflowControl()
        control.coordinate_path("op-1", make_request(), sections(),
                                guard_minutes=5, at=at())
        with self.assertRaises(CommitError):
            control.coordinate_path("op-1-replayed", make_request(),
                                    sections(), guard_minutes=5, at=at())
        # Nothing leaked from the failed attempt.
        self.assertEqual(control.path_ledger.version, 1)
        self.assertEqual(control.stream.head, 1)
        self.assertEqual(len(control.trail._rows), 1)
        self.assertTrue(control.stream.verify_chain())
        self.assertTrue(control.trail.verify())

    def test_rejection_replay_is_also_idempotent(self):
        control = RailForgeWorkflowControl()
        meet = [Traversal("T9", "A-B", "BJ", at(8, 10), at(8, 40), -1, "rx")]
        args = ("op-meet", make_request(rid="r2", max_delay=0), sections())
        first = control.coordinate_path(*args, occupancies=meet,
                                        guard_minutes=5, at=at())
        second = control.coordinate_path(*args, occupancies=meet,
                                         guard_minutes=5, at=at())
        self.assertIs(first, second)
        self.assertEqual(control.stream.head, 1)
        self.assertEqual(control.path_ledger.version, 0)


class FailingEventStream(EventStream):
    """Fails once when the stream reaches ``fail_on``, then recovers."""

    def __init__(self, fail_on: int = 2):
        super().__init__()
        self.fail_on = fail_on
        self.failed = False

    def publish(self, *args, **kwargs):
        if not self.failed and self.head + 1 == self.fail_on:
            self.failed = True
            raise RuntimeError("simulated cursor broker outage")
        return super().publish(*args, **kwargs)


class ExplodingTrail(Trail):
    def append(self, *args, **kwargs):
        raise RuntimeError("simulated audit sink outage")


class RollbackTests(unittest.TestCase):
    def _seed(self, control):
        # One healthy committed plan so checkpoints sit in the middle of state.
        control.coordinate_path("seed", make_request(rid="seed", train="T0"),
                                sections(), guard_minutes=5, at=at())

    def test_event_broker_failure_rolls_back_plan_store_and_ledger(self):
        stream = FailingEventStream(fail_on=2)
        control = RailForgeWorkflowControl(stream=stream)
        self._seed(control)
        self.assertEqual(control.path_ledger.version, 1)
        req = make_request(rid="after-fail", train="T1",
                           ready=at(10), due=at(13))
        with self.assertRaises(RuntimeError):
            control.coordinate_path("op-fail", req, sections(),
                                    guard_minutes=5, at=at())
        # Ledger, plan store, stream and audit all look exactly as after seed.
        self.assertEqual(control.path_ledger.version, 1)
        held = {t.request_id for t in control.path_ledger.snapshot().traversals}
        self.assertEqual(held, {"seed"})
        self.assertIsNone(control.store.read("coordination.plan:after-fail"))
        self.assertEqual(control.stream.head, 1)
        self.assertEqual(len(control.trail._rows), 1)
        self.assertTrue(control.stream.verify_chain())
        self.assertTrue(control.trail.verify())
        # Control is still usable after the rollback.
        retry = control.coordinate_path("op-ok", make_request(
            rid="after-fail", train="T1", ready=at(10), due=at(13),
            version=None),
            sections(), guard_minutes=5, at=at())
        self.assertEqual(retry.event.payload["status"], "committed")
        self.assertEqual(control.path_ledger.version, 2)

    def test_audit_failure_rolls_back_event_and_ledger(self):
        control = RailForgeWorkflowControl(trail=ExplodingTrail())
        with self.assertRaises(RuntimeError):
            control.coordinate_path("op-audit-fail", make_request(),
                                    sections(), guard_minutes=5, at=at())
        self.assertEqual(control.path_ledger.version, 0)
        self.assertEqual(control.path_ledger.snapshot().traversals, ())
        self.assertEqual(control.stream.head, 0)
        self.assertIsNone(control.store.read("coordination.plan:r1"))
        self.assertTrue(control.stream.verify_chain())

    def test_rollback_after_seed_keeps_stream_hash_chain_intact(self):
        stream = FailingEventStream(fail_on=3)
        control = RailForgeWorkflowControl(stream=stream)
        self._seed(control)
        # A second healthy plan bumps to event 2.
        control.coordinate_path("second-seed", make_request(
            rid="seed2", train="T2", ready=at(11), due=at(14), version=None),
            sections(), guard_minutes=5, at=at())
        req = make_request(rid="boom", train="T3", ready=at(12), due=at(15))
        with self.assertRaises(RuntimeError):
            control.coordinate_path("op-boom", req, sections(),
                                    guard_minutes=5, at=at())
        self.assertTrue(control.stream.verify_chain())
        self.assertEqual(control.stream.head, 2)
        self.assertEqual(control.path_ledger.version, 2)


class BatchAtomicTests(unittest.TestCase):
    def test_batch_priority_decisions_all_published(self):
        control = RailForgeWorkflowControl()
        low = make_request("lo", "LO", priority=1, max_delay=0, direction=1,
                           version=None)
        high = make_request("hi", "HI", priority=9, max_delay=0, direction=-1,
                            ready=at(8, 5), version=None)
        receipt = control.coordinate_paths("batch-1", [low, high], sections(),
                                           at=at())
        self.assertEqual(receipt.result["accepted"], ["hi"])
        self.assertEqual(receipt.result["rejected"], ["lo"])
        low_decision = next(d for d in receipt.result["decisions"]
                            if d.request_id == "lo")
        self.assertEqual(low_decision.rejection.reason, SINGLE_TRACK_MEET)
        # Two per-request events plus the batch summary event.
        self.assertEqual(control.stream.head, 3)
        self.assertTrue(control.path_ledger.contains_request("hi"))
        self.assertFalse(control.path_ledger.contains_request("lo"))
        self.assertTrue(control.stream.verify_chain())
        self.assertTrue(control.trail.verify())

    def test_batch_replay_is_idempotent(self):
        control = RailForgeWorkflowControl()
        low = make_request("lo", "LO", route=("C-D",), priority=1, version=None)
        high = make_request("hi", "HI", route=("C-D",), priority=9,
                            ready=at(9), due=at(12), version=None)
        first = control.coordinate_paths("batch-x", [low, high], sections(),
                                         at=at())
        second = control.coordinate_paths("batch-x", [low, high], sections(),
                                          at=at())
        self.assertIs(first, second)
        self.assertEqual(control.path_ledger.version, 2)
        self.assertEqual(control.stream.head, 3)

    def test_batch_duplicate_request_is_refused_before_any_write(self):
        control = RailForgeWorkflowControl()
        low = make_request("lo", "LO", route=("C-D",), priority=1, version=None)
        high = make_request("hi", "HI", route=("C-D",), priority=9,
                            ready=at(9), due=at(12), version=None)
        control.coordinate_paths("batch-x", [low, high], sections(), at=at())
        head = control.stream.head
        with self.assertRaises(CommitError):
            control.coordinate_paths("batch-y", [low], sections(), at=at())
        self.assertEqual(control.stream.head, head)
        self.assertEqual(control.path_ledger.version, 2)

    def test_batch_summary_event_failure_rolls_back_whole_batch(self):
        # Two accepted plans emit two committed events; the batch summary is
        # event number 3. Failing it must undo plans, ledger and per-request
        # events alike.
        stream = FailingEventStream(fail_on=3)
        control = RailForgeWorkflowControl(stream=stream)
        first = make_request("a", "A", route=("C-D",), version=None)
        second = make_request("b", "B", route=("C-D",), priority=9,
                              ready=at(9), due=at(12), version=None)
        with self.assertRaises(RuntimeError):
            control.coordinate_paths("batch-fail", [first, second], sections(),
                                     at=at())
        self.assertEqual(control.path_ledger.version, 0)
        self.assertEqual(control.path_ledger.snapshot().traversals, ())
        self.assertIsNone(control.store.read("coordination.plan:a"))
        self.assertIsNone(control.store.read("coordination.plan:b"))
        self.assertEqual(control.stream.head, 0)
        self.assertEqual(len(control.trail._rows), 0)
        self.assertTrue(control.stream.verify_chain())
        self.assertTrue(control.trail.verify())


class ConcurrencyTests(unittest.TestCase):
    def test_concurrent_requests_are_serialized_without_double_occupancy(self):
        control = RailForgeWorkflowControl()
        barrier = Barrier(4)
        errors: list[Exception] = []

        def worker(idx):
            barrier.wait()
            try:
                # All four want the same single-track slot 08:00-08:30; only
                # one can win.
                req = make_request(f"c{idx}", f"T{idx}", max_delay=0,
                                   route=("A-B",), version=None)
                control.coordinate_path(f"conc-{idx}", req, sections(),
                                        guard_minutes=5, at=at())
            except CommitError:
                errors.append("commit")
            except Exception as exc:  # pragma: no cover - surfaced in assertion
                errors.append(exc)

        threads = [Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        accepted = [t.section for t in control.path_ledger.snapshot().traversals]
        self.assertEqual(accepted, ["A-B"])
        self.assertEqual(control.path_ledger.version, 1)
        self.assertTrue(control.stream.verify_chain())
        self.assertTrue(control.trail.verify())
        # The three losers were published as explainable rejections, not errors.
        committed_events = [e for e in control.stream.snapshot()
                            if e.payload.get("status") == "committed"]
        rejected_events = [e for e in control.stream.snapshot()
                           if e.payload.get("status") == "rejected"]
        self.assertEqual(len(committed_events), 1)
        self.assertEqual(len(rejected_events), 3)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
