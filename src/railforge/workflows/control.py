from __future__ import annotations

from dataclasses import dataclass, is_dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from threading import RLock
from typing import Any, Callable, Mapping, TypeVar

from railforge.audit.trail import Trail
from railforge.braking.brake_percentage import brake_percentage
from railforge.billing.demurrage import charge
from railforge.cargo.segregation import violations
from railforge.consist.integrity import validate
from railforge.coordination.paths import (
    CommitError,
    CoordinationRequest,
    Decision,
    PathLedger,
    Rejection,
    STALE_VERSION,
    batch_coordinate,
    coordinate,
)
from railforge.customs.holds import active
from railforge.energy.regen import net_energy
from railforge.eta.event_fusion import fused_delay
from railforge.events.cursor import CursorConsumer, FeedEvent
from railforge.events.stream import EventStream
from railforge.intermodal.connections import feasible
from railforge.inventory.wagon_pool import allocate
from railforge.locomotive.tractive_effort import available_effort
from railforge.maintenance.release import releasable
from railforge.possession.windows import conflicts as possession_conflicts
from railforge.routing.clearance import route_ok
from railforge.signaling.block_occupancy import reserve
from railforge.storage.ops_store import VersionedStore
from railforge.timetable.meets import conflicts as meet_conflicts
from railforge.wagon.axle_load import route_ok as axle_route_ok
from railforge.yard.hump import classify
from railforge.yard.switching import lock_route
from railforge.crew.duty import legal as duty_legal

T = TypeVar("T")
BROKEN_CONTROL_TOPICS: set[str] = set()


def _safe(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _safe(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


@dataclass(frozen=True)
class OperationReceipt:
    operation_id: str
    topic: str
    subject: str
    result: Any
    event: Any
    audit_index: int
    version: int


class RailForgeWorkflowControl:
    """Atomic domain -> event -> audit workflow used by every feature surface."""

    def __init__(self, stream: EventStream | None = None, trail: Trail | None = None,
                 store: VersionedStore | None = None, ledger: PathLedger | None = None):
        self.stream = stream or EventStream()
        self.trail = trail or Trail()
        self.store = store or VersionedStore()
        self.path_ledger = ledger or PathLedger()
        self._receipts: dict[str, OperationReceipt] = {}
        self._consumers: dict[str, CursorConsumer] = {}
        self._coordination_lock = RLock()

    @property
    def receipts(self) -> Mapping[str, OperationReceipt]:
        return dict(self._receipts)

    def _commit(self, operation_id: str, topic: str, subject: str, at: datetime,
                action: Callable[[], T], evidence: Mapping[str, Any] | None = None) -> OperationReceipt:
        previous = self._receipts.get(operation_id)
        if previous is not None:
            if previous.topic != topic or previous.subject != subject:
                raise ValueError("operation id reused for a different workflow")
            return previous
        result = action()
        version = self.store.write(subject, _safe(result))
        payload = {
            "operation_id": operation_id,
            "status": "committed",
            "control_path": "legacy" if topic in BROKEN_CONTROL_TOPICS else "atomic",
            "version": version,
            "result": _safe(result),
            **dict(evidence or {}),
        }
        event = self.stream.publish(operation_id, at, topic, subject, payload)
        audit = self.trail.append("railforge-control", topic, subject, at)
        receipt = OperationReceipt(operation_id, topic, subject, result, event, audit.index, version)
        self._receipts[operation_id] = receipt
        return receipt

    def run(self, operation_id: str, topic: str, subject: str, at: datetime,
            action: Callable[[], T], evidence: Mapping[str, Any] | None = None) -> OperationReceipt:
        return self._commit(operation_id, topic, subject, at, action, evidence)

    def reserve_block(self, operation_id, candidate, existing, clearance, at):
        return self._commit(operation_id, "dispatch.block.reserved", candidate.train, at,
                            lambda: reserve(candidate, existing, clearance))

    def validate_consist(self, operation_id, rows, subject, at):
        return self._commit(operation_id, "consist.validated", subject, at, lambda: validate(rows))

    def assess_brakes(self, operation_id, rows, gradient, subject, at):
        return self._commit(operation_id, "braking.assessed", subject, at,
                            lambda: brake_percentage(rows, gradient))

    def plan_traction(self, operation_id, rows, adhesion_factor, subject, at):
        return self._commit(operation_id, "traction.planned", subject, at,
                            lambda: available_effort(rows, adhesion_factor))

    def assign_duty(self, operation_id, rows, max_duty, max_drive, max_span, subject, at):
        def action():
            result = duty_legal(rows, max_duty, max_drive, max_span)
            if not result:
                raise ValueError("duty is not legal")
            return result
        return self._commit(operation_id, "crew.duty.assigned", subject, at, action)

    def book_meet(self, operation_id, rows, subject, at):
        return self._commit(operation_id, "timetable.meet.booked", subject, at,
                            lambda: meet_conflicts(rows))

    def classify_yard(self, operation_id, cuts, tracks, occupied, subject, at):
        return self._commit(operation_id, "yard.classified", subject, at,
                            lambda: classify(cuts, tracks, occupied))

    def check_axles(self, operation_id, wagon, max_axle, max_gross, subject, at):
        return self._commit(operation_id, "wagon.axle.checked", subject, at,
                            lambda: axle_route_ok(wagon, max_axle, max_gross))

    def book_intermodal(self, operation_id, inbound, outbound, unload, load, cutoff, subject, at):
        return self._commit(operation_id, "intermodal.booked", subject, at,
                            lambda: feasible(inbound, outbound, unload, load, cutoff))

    def protect_possession(self, operation_id, candidate, rows, subject, at):
        return self._commit(operation_id, "possession.protected", subject, at,
                            lambda: possession_conflicts(candidate, rows))

    def release_maintenance(self, operation_id, evidence, policy, check_at, subject, at):
        def action():
            result = releasable(evidence, policy, check_at)
            if not result:
                raise ValueError("maintenance evidence incomplete")
            return result
        return self._commit(operation_id, "maintenance.released", subject, at, action)

    def consume_event(self, operation_id, event: FeedEvent, subject, at):
        consumer = self._consumers.setdefault(event.partition, CursorConsumer())
        return self._commit(operation_id, "events.cursor.consumed", subject, at,
                            lambda: consumer.accept(event))

    def charge_demurrage(self, operation_id, arrival, release, tariff, subject, at):
        return self._commit(operation_id, "billing.demurrage.charged", subject, at,
                            lambda: charge(arrival, release, tariff))

    def check_customs(self, operation_id, rows, scope, check_at, subject, at):
        return self._commit(operation_id, "customs.hold.checked", subject, at,
                            lambda: active(rows, scope, check_at))

    def check_segregation(self, operation_id, rows, rules, subject, at):
        return self._commit(operation_id, "cargo.segregation.checked", subject, at,
                            lambda: violations(rows, rules))

    def calculate_energy(self, operation_id, rows, subject, at):
        return self._commit(operation_id, "energy.calculated", subject, at,
                            lambda: net_energy(rows))

    def lock_switch_route(self, operation_id, route, switches, owner, subject, at):
        return self._commit(operation_id, "yard.route.locked", subject, at,
                            lambda: lock_route(route, switches, owner))

    def check_clearance(self, operation_id, profile, segments, subject, at):
        return self._commit(operation_id, "routing.clearance.checked", subject, at,
                            lambda: route_ok(profile, segments))

    def allocate_wagons(self, operation_id, rows, wagon_type, location, on, count, required_days, forbidden, subject, at):
        return self._commit(operation_id, "inventory.wagons.allocated", subject, at,
                            lambda: allocate(rows, wagon_type, location, on, count, required_days, forbidden))

    def fuse_eta(self, operation_id, rows, max_lateness, subject, at):
        return self._commit(operation_id, "eta.fused", subject, at,
                            lambda: fused_delay(rows, max_lateness))

    # ------------------------------------------------------------------
    # Cross-bureau freight path coordination
    # ------------------------------------------------------------------

    @staticmethod
    def _plan_key(request_id: str) -> str:
        return f"coordination.plan:{request_id}"

    @staticmethod
    def _rejection_payload(rejection) -> dict:
        return {
            "reason": rejection.reason,
            "detail": rejection.detail,
            "sections": list(rejection.sections),
            "blocking_trains": list(rejection.blocking_trains),
            "expected_version": rejection.expected_version,
            "actual_version": rejection.actual_version,
            "latest_departure": (rejection.latest_departure.isoformat()
                                 if rejection.latest_departure else None),
        }

    def coordinate_path(self, operation_id: str, request: CoordinationRequest,
                        sections, occupancies=(), guard_minutes: int = 0,
                        at: datetime | None = None):
        """Atomically coordinate one cross-bureau freight path.

        Accepted request: plan + cursor event + audit row are written as one
        unit and the shared path ledger gains the occupied sections. Replaying
        the same ``operation_id`` returns the original receipt and never
        occupies a section twice.

        Rejected request: no state changes (no ledger bump, no plan row); the
        returned receipt carries the explainable rejection.
        """
        at = at or datetime.now(timezone.utc)
        with self._coordination_lock:
            previous = self._receipts.get(operation_id)
            if previous is not None:
                if previous.subject != request.train:
                    raise ValueError("operation id reused for a different workflow")
                return previous

            if self.path_ledger.contains_request(request.request_id):
                # Same request under a new operation id: the plan already owns
                # its sections. Refuse before any write instead of emitting a
                # misleading rejection or a second occupancy.
                raise CommitError(
                    f"request {request.request_id} is already committed; "
                    "replay the original operation id for an idempotent result"
                )

            # Optimistic concurrency: a request built on an outdated planning
            # version is refused with an explainable STALE_VERSION before any
            # section or block is even examined.
            current_version = self.path_ledger.version
            if request.expected_version is not None and request.expected_version != current_version:
                rejection = Rejection(
                    request.request_id, request.train, STALE_VERSION, (), (),
                    (f"planning version {request.expected_version} is stale; "
                     f"current version is {current_version}; refetch before retrying"),
                    expected_version=request.expected_version,
                    actual_version=current_version,
                )
                decision = Decision(False, request.request_id, request.train,
                                    rejection=rejection)
            else:
                decision = coordinate(request, sections, occupancies,
                                      guard_minutes, ledger=self.path_ledger,
                                      ledger_version=current_version)
            if not decision.accepted:
                rejection = decision.rejection
                payload = {
                    "operation_id": operation_id,
                    "status": "rejected",
                    "control_path": "atomic",
                    "rejection": self._rejection_payload(rejection),
                }
                event = self.stream.publish(
                    operation_id, at, "coordination.path.rejected",
                    request.train, payload,
                )
                audit = self.trail.append("railforge-control",
                                          "coordination.path.rejected",
                                          request.train, at)
                receipt = OperationReceipt(operation_id,
                                           "coordination.path.rejected",
                                           request.train, decision, event,
                                           audit.index,
                                           self.path_ledger.version)
                self._receipts[operation_id] = receipt
                return receipt

            candidate = decision.candidate
            # Atomic phase: stage every write, roll all of them back if any
            # later step fails so a plan can never exist without its sections,
            # cursor event and audit row.
            stream_cp = self.stream.checkpoint()
            trail_cp = self.trail.checkpoint()
            store_cp = self.store.snapshot()
            ledger_cp = self.path_ledger.snapshot()
            try:
                version = self.path_ledger.add(
                    candidate,
                    expected_version=request.expected_version,
                    guard_minutes=guard_minutes,
                )
                plan = _safe(candidate)
                store_version = self.store.write(self._plan_key(request.request_id),
                                                 {"status": "committed", "plan": plan,
                                                  "ledger_version": version})
                payload = {
                    "operation_id": operation_id,
                    "status": "committed",
                    "control_path": "atomic",
                    "request_id": request.request_id,
                    "ledger_version": version,
                    "version": store_version,
                    "bureaus": list(candidate.bureaus),
                    "handoffs": [list(h) for h in candidate.handoffs],
                    "delay_minutes": candidate.delay_minutes,
                    "plan": plan,
                }
                event = self.stream.publish(
                    operation_id, at, "coordination.path.committed",
                    request.train, payload,
                )
                audit = self.trail.append("railforge-control",
                                          "coordination.path.committed",
                                          request.train, at)
            except Exception:
                self.path_ledger.restore(ledger_cp)
                self.store.restore(store_cp)
                self.stream.restore(stream_cp)
                self.trail.restore(trail_cp)
                raise

            receipt = OperationReceipt(operation_id,
                                       "coordination.path.committed",
                                       request.train, decision, event,
                                       audit.index, version)
            self._receipts[operation_id] = receipt
            return receipt

    def coordinate_paths(self, operation_id: str, requests, sections,
                         occupancies=(), guard_minutes: int = 0,
                         at: datetime | None = None):
        """Coordinate a batch of requests priority-first under one operation.

        The whole batch is one transaction: the decisions are computed without
        touching shared state, then every accepted plan is staged together.
        Any ledger collision at commit time rolls the entire batch back.
        """
        at = at or datetime.now(timezone.utc)
        with self._coordination_lock:
            previous = self._receipts.get(operation_id)
            if previous is not None:
                return previous

            duplicate = next((r.request_id for r in requests
                              if self.path_ledger.contains_request(r.request_id)),
                             None)
            if duplicate is not None:
                raise CommitError(
                    f"request {duplicate} is already committed; "
                    "replay the original operation id for an idempotent result"
                )

            current_version = self.path_ledger.version
            stale = next((r for r in requests
                          if r.expected_version is not None
                          and r.expected_version != current_version), None)
            if stale is not None:
                rejection = Rejection(
                    stale.request_id, stale.train, STALE_VERSION, (), (),
                    (f"planning version {stale.expected_version} is stale; "
                     f"current version is {current_version}; refetch before retrying"),
                    expected_version=stale.expected_version,
                    actual_version=current_version,
                )
                event = self.stream.publish(
                    f"{operation_id}:{stale.request_id}", at,
                    "coordination.path.rejected", stale.train, {
                        "operation_id": operation_id,
                        "request_id": stale.request_id,
                        "status": "rejected",
                        "control_path": "atomic",
                        "rejection": self._rejection_payload(rejection),
                    },
                )
                audit = self.trail.append("railforge-control",
                                          "coordination.path.rejected",
                                          stale.train, at)
                decision = Decision(False, stale.request_id, stale.train,
                                    rejection=rejection)
                receipt = OperationReceipt(
                    operation_id, "coordination.path.rejected", stale.train,
                    {"decisions": [decision], "accepted": [],
                     "rejected": [stale.request_id],
                     "ledger_version": current_version},
                    event, audit.index, current_version,
                )
                self._receipts[operation_id] = receipt
                return receipt

            scratch = PathLedger()
            decisions = batch_coordinate(requests, sections, occupancies,
                                         guard_minutes, ledger=scratch)

            stream_cp = self.stream.checkpoint()
            trail_cp = self.trail.checkpoint()
            store_cp = self.store.snapshot()
            ledger_cp = self.path_ledger.snapshot()
            try:
                for decision in decisions:
                    if not decision.accepted:
                        rejection = decision.rejection
                        self.stream.publish(
                            f"{operation_id}:{decision.request_id}", at,
                            "coordination.path.rejected", decision.train, {
                                "operation_id": operation_id,
                                "request_id": decision.request_id,
                                "status": "rejected",
                                "control_path": "atomic",
                                "rejection": self._rejection_payload(rejection),
                            },
                        )
                        self.trail.append("railforge-control",
                                          "coordination.path.rejected",
                                          decision.train, at)
                        continue
                    candidate = decision.candidate
                    version = self.path_ledger.add(
                        candidate, guard_minutes=guard_minutes)
                    plan = _safe(candidate)
                    self.store.write(self._plan_key(candidate.request_id),
                                     {"status": "committed", "plan": plan,
                                      "ledger_version": version})
                    self.stream.publish(
                        f"{operation_id}:{candidate.request_id}", at,
                        "coordination.path.committed", candidate.train, {
                            "operation_id": operation_id,
                            "request_id": candidate.request_id,
                            "status": "committed",
                            "control_path": "atomic",
                            "ledger_version": version,
                            "bureaus": list(candidate.bureaus),
                            "handoffs": [list(h) for h in candidate.handoffs],
                            "delay_minutes": candidate.delay_minutes,
                            "plan": plan,
                        },
                    )
                    self.trail.append("railforge-control",
                                      "coordination.path.committed",
                                      candidate.train, at)

                result = {"decisions": decisions,
                          "accepted": [d.request_id for d in decisions if d.accepted],
                          "rejected": [d.request_id for d in decisions if not d.accepted],
                          "ledger_version": self.path_ledger.version}
                summary_event = self.stream.publish(
                    operation_id, at, "coordination.batch.committed", operation_id,
                    {"operation_id": operation_id, "status": "committed",
                     "control_path": "atomic",
                     "accepted": result["accepted"], "rejected": result["rejected"],
                     "ledger_version": result["ledger_version"]},
                )
                summary_audit = self.trail.append("railforge-control",
                                                  "coordination.batch.committed",
                                                  operation_id, at)
            except Exception:
                self.path_ledger.restore(ledger_cp)
                self.store.restore(store_cp)
                self.stream.restore(stream_cp)
                self.trail.restore(trail_cp)
                raise

            receipt = OperationReceipt(operation_id,
                                       "coordination.batch.committed",
                                       operation_id, result, summary_event,
                                       summary_audit.index,
                                       self.path_ledger.version)
            self._receipts[operation_id] = receipt
            return receipt

