"""SCADA_V2 @ 300 mm integration-acceptance case definitions.

Everything here is DESIGN INPUT (PATH centre lines). Expected topology is derived below in plain Python,
independently of the Router, the diagnostics tool and AutoCAD.  Width scope: 300 mm only.
"""
from __future__ import annotations

import math

WIDTH = 300.0
PROFILE = "SCADA_V2"

# case id -> dict(window=(xmin,xmax,ymin,ymax), paths=[[(x,y),...],...], note)
CASES: dict[str, dict] = {
    # Case A: Straight -> Elbow -> Straight, four turn directions
    "A1_W+N": dict(window=(-4000, 1000, -1000, 4000), note="Straight-Elbow-Straight, arms W+N",
                   paths=[[(-3000, 0), (0, 0), (0, 3000)]]),
    "A2_W+S": dict(window=(6000, 11000, -4000, 1000), note="arms W+S",
                   paths=[[(7000, 0), (10000, 0), (10000, -3000)]]),
    "A3_E+S": dict(window=(19000, 24000, -4000, 1000), note="arms E+S",
                   paths=[[(23000, 0), (20000, 0), (20000, -3000)]]),
    "A4_E+N": dict(window=(29000, 34000, -1000, 4000), note="arms E+N",
                   paths=[[(33000, 0), (30000, 0), (30000, 3000)]]),
    # Case B: Tee with main incoming, main outgoing and branch (branch N, S, W, E orientations)
    "B1_TEE_branch_N": dict(window=(38000, 43000, -1000, 4000), note="Tee, branch N",
                            paths=[[(39000, 0), (42000, 0)], [(40500, 3000), (40500, 0)]]),
    "B2_TEE_branch_S": dict(window=(44000, 49000, -4000, 1000), note="Tee, branch S",
                            paths=[[(45000, 0), (48000, 0)], [(46500, -3000), (46500, 0)]]),
    "B3_TEE_branch_W": dict(window=(50000, 55000, -2500, 2500), note="Tee, branch W (main N-S)",
                            paths=[[(52500, -2000), (52500, 2000)], [(51000, 0), (52500, 0)]]),
    "B4_TEE_branch_E": dict(window=(56000, 61000, -2500, 2500), note="Tee, branch E (main N-S)",
                            paths=[[(58500, -2000), (58500, 2000)], [(58500, 0), (60000, 0)]]),
    # Case C: Cross, W E N S all connected
    "C1_CROSS": dict(window=(62000, 68000, -3500, 3500), note="Cross, four arms",
                     paths=[[(63000, 0), (67000, 0)], [(65000, 3000), (65000, -3000)]]),
    # Case D: multi-junction chain  Straight-Elbow-Straight-Tee-Straight-Elbow-Straight-Cross-Straight
    "D1_CHAIN": dict(window=(-1000, 13000, 9000, 22000), note="chain: Elbow, Tee, Elbow, Cross in one routing",
                     paths=[[(0, 10000), (4000, 10000), (4000, 18000), (12000, 18000)],
                            [(4000, 14000), (7000, 14000)],
                            [(9000, 15000), (9000, 21000)]]),
    # Case E: consecutive direction changes  East -> North -> West -> North
    "E1_TURNS_long": dict(window=(-1000, 4500, 28000, 37000), note="E,N,W,N turns, long middle segments",
                          paths=[[(0, 30000), (3000, 30000), (3000, 33000), (500, 33000), (500, 36000)]]),
    "E2_TURNS_short": dict(window=(9000, 13500, 28000, 37000), note="E,N,W,N turns, short middle segments (800 mm)",
                           paths=[[(10000, 30000), (12000, 30000), (12000, 30800), (11200, 30800), (11200, 33000)]]),
}


def _seg_params(path):
    return [(path[i], path[i + 1]) for i in range(len(path) - 1)]


def _on_seg(p, a, b, tol=1e-6):
    ab = (b[0] - a[0], b[1] - a[1])
    l2 = ab[0] ** 2 + ab[1] ** 2
    t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / l2
    q = (a[0] + t * ab[0], a[1] + t * ab[1])
    return 0 <= t <= 1 and math.dist(p, q) <= tol, t


def _cross(a, b, c, d):
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    if 1e-9 < t < 1 - 1e-9 and 1e-9 < u < 1 - 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def direction(dx, dy):
    if abs(dy) < 1e-9 and dx > 0:
        return "E"
    if abs(dy) < 1e-9 and dx < 0:
        return "W"
    if abs(dx) < 1e-9 and dy > 0:
        return "N"
    if abs(dx) < 1e-9 and dy < 0:
        return "S"
    raise ValueError("non-orthogonal")


def classify(dirs):
    d = set(dirs)
    n = len(d)
    ew, ns = {"E", "W"} <= d, {"N", "S"} <= d
    if n == 1:
        return "END"
    if n == 2:
        return "STRAIGHT" if (ew or ns) else "ELBOW"
    if n == 3:
        return "TEE"
    if n == 4:
        return "CROSS"
    return "UNKNOWN"


def topology(paths):
    """-> (nodes, edges).  nodes: {pt: {'dirs': [..], 'type': str}}, edges: [(a, b, length, dir_a_to_b)]."""
    segs = []
    for p in paths:
        segs += _seg_params(p)
    nodes: list[tuple] = []

    def add(pt):
        pt = (round(pt[0], 6), round(pt[1], 6))
        if pt not in nodes:
            nodes.append(pt)

    for a, b in segs:
        add(a)
        add(b)
    for i, (a, b) in enumerate(segs):
        for j, (c, d) in enumerate(segs):
            if i != j:
                x = _cross(a, b, c, d)
                if x:
                    add(x)
    edges = set()
    for a, b in segs:
        on = []
        for n in nodes:
            ok, t = _on_seg(n, a, b)
            if ok:
                on.append((t, n))
        on.sort()
        for (_, p), (_, q) in zip(on, on[1:]):
            edges.add((p, q) if p < q else (q, p))
    info = {n: [] for n in nodes}
    out_edges = []
    for p, q in sorted(edges):
        length = math.dist(p, q)
        out_edges.append((p, q, length))
        info[p].append(direction(q[0] - p[0], q[1] - p[1]))
        info[q].append(direction(p[0] - q[0], p[1] - q[1]))
    return ({n: dict(dirs=sorted(d, key="EWNS".index), type=classify(d)) for n, d in info.items()}, out_edges)


def expected_fittings(case):
    nodes, _ = topology(CASES[case]["paths"])
    return {n: v for n, v in nodes.items() if v["type"] in ("ELBOW", "TEE", "CROSS")}
