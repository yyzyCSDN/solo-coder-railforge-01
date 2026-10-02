from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass

@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    enabled: bool = True
    cost: float = 1.0

def reachable(edges: list[Edge], starts: set[str]) -> set[str]:
    adj = defaultdict(list)
    for e in edges:
        if e.enabled:
            adj[e.source].append(e.target)
    seen = set(starts)
    q = deque(starts)
    while q:
        x = q.popleft()
        for y in adj[x]:
            if y not in seen:
                seen.add(y)
                q.append(y)
    return seen

def shortest_cost(edges: list[Edge], source: str, target: str):
    import heapq
    adj = defaultdict(list)
    for e in edges:
        if e.enabled and e.cost >= 0:
            adj[e.source].append((e.target, e.cost))
    pq = [(0.0, source, ())]
    best = {}
    while pq:
        cost, node, path = heapq.heappop(pq)
        if node in best and best[node] <= cost:
            continue
        best[node] = cost
        new = path + (node,)
        if node == target:
            return (cost, list(new))
        for nxt, w in adj[node]:
            heapq.heappush(pq, (cost + w, nxt, new))
    return None
