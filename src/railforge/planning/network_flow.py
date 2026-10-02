from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import heapq

@dataclass(frozen=True)
class Arc:
    arc_id: str
    source: str
    target: str
    capacity: int
    cost: float
    enabled: bool = True

@dataclass(frozen=True)
class Demand:
    commodity: str
    source: str
    target: str
    units: int
    priority: int

def shortest_path(arcs: list[Arc], source: str, target: str, residual: dict[str, int]):
    adj = defaultdict(list)
    for a in arcs:
        if a.enabled and residual.get(a.arc_id, a.capacity) > 0:
            adj[a.source].append(a)
    pq = [(0.0, source, ())]
    best = {}
    while pq:
        cost, node, path = heapq.heappop(pq)
        if node in best and best[node] <= cost:
            continue
        best[node] = cost
        if node == target:
            return (list(path), cost)
        for a in adj[node]:
            heapq.heappush(pq, (cost + a.cost, a.target, path + (a.arc_id,)))
    return None

def allocate(arcs: list[Arc], demands: list[Demand]):
    residual = {a.arc_id: a.capacity for a in arcs}
    assigned = {}
    rejected = []
    arcmap = {a.arc_id: a for a in arcs}
    for d in sorted(demands, key=lambda x: (-x.priority, -x.units, x.commodity)):
        need = d.units
        paths = []
        while need > 0:
            result = shortest_path(arcs, d.source, d.target, residual)
            if result is None:
                break
            path, _ = result
            bottleneck = min((residual[x] for x in path))
            take = min(need, bottleneck)
            if take <= 0:
                break
            for aid in path:
                residual[aid] -= take
            paths.append((tuple(path), take))
            need -= take
        if need:
            rejected.append((d.commodity, need))
        assigned[d.commodity] = paths
    return (assigned, rejected, residual)

def arc_utilization(arcs, residual):
    return {a.arc_id: 0.0 if a.capacity <= 0 else (a.capacity - residual.get(a.arc_id, a.capacity)) / a.capacity for a in arcs}
