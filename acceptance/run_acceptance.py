"""SCADA_V2 integration acceptance (engine part, items 1-8) for ONE width per run: ACC_WIDTH=150|300|450|600 (default 300).

    python acceptance/run_acceptance.py            # build (if needed), diagnose, census, analyse, write evidence/
    python acceptance/run_acceptance.py --rebuild  # rebuild the acceptance DWG first

Read-only on everything except: the NEW acceptance DWG and the files under acceptance/evidence/.
Items 9 (SAVE/REOPEN in the GUI) and 10 (GUI visual agreement) are NEVER judged here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(HERE))
import accore_run  # noqa: E402
import build_drawing  # noqa: E402
from cases import CASES, WIDTH, topology, direction  # noqa: E402

W_TAG = "" if WIDTH == 300.0 else "_%d" % WIDTH
DWG = HERE / ("scada_v2_%d_acceptance.dwg" % WIDTH)
EVID = HERE / ("evidence" + W_TAG)
ROUTER_DIR = Path(r"D:\github\ezdxf\scada-v2-block-integration\router")
TOL = 0.01            # mm; = diagnostics connection_exact_mm
RAIL_T, RUNG_W, RUNG_SP, RUNG_FIRST = 20.0, 40.0, 250.0, 125.0   # documented Router ladder rule (cable_tray_router.lsp)
RUNG_HALF = WIDTH / 2 - RAIL_T     # Router ctr-draw-straight-ladder: rung lateral half-length = width/2 - thickness
RAIL_OUTER = WIDTH / 2 + RAIL_T / 2
RAIL_INNER = WIDTH / 2 - RAIL_T / 2 # rail centre-line at +-width/2, thickness 20 -> inner edge at +-140
ZONE = 700.0          # candidate-entity radius around a junction, mm
OPP = {"E": "W", "W": "E", "N": "S", "S": "N"}
UNIT = {"E": (1, 0), "W": (-1, 0), "N": (0, 1), "S": (0, -1)}


# ---------------------------------------------------------------- engine runs
def run_diagnostics_and_census(dwg: Path, work: Path):
    cmds = ['(setq ard:out-dir "%s/")' % (work / "diag").as_posix(),
            '(setq ard:run-note "acceptance run on a scratch COPY of %s")' % dwg.as_posix(),
            '(ard:guarded "all" nil "CTRDIAGALL")',
            '(cs:run "%s")' % (work / "census.tsv").as_posix()]
    log, info = accore_run.run([REPO / "autocad_router_diagnostics.lsp", HERE / "census.lsp"], cmds,
                               work / "engine", drawing=dwg, timeout=900)
    diag = json.loads(next((work / "diag").glob("*_all.json")).read_text(encoding="utf-8"))
    return diag, parse_census(work / "census.tsv"), info


def parse_census(path: Path):
    rows, count = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if f[0] == "SSGET_COUNT":
            count = int(f[1])
            continue
        h, typ, layer, layout, name, tag, geom = f
        if typ == "INSERT":
            x, y, rot, sc = (float(v) for v in geom.split(","))
            rows.append(dict(handle=h, type=typ, layer=layer, layout=layout, name=name, tag=tag, ins=(x, y), rot=rot, scale=sc, verts=[]))
        else:
            v = [tuple(float(c) for c in p.split(",")) for p in geom.split(";")] if geom else []
            rows.append(dict(handle=h, type=typ, layer=layer, layout=layout, name=name, tag=tag, ins=None, rot=None, scale=None, verts=v))
    return dict(ssget_count=count, rows=rows)


def build_to_scratch(router_src: str, label: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="acc_base_")) / "router.lsp"
    tmp.write_text(router_src, encoding="utf-8")
    out = Path(tempfile.mkdtemp(prefix="acc_base_dwg_")) / (label + ".dwg")
    build_drawing.build(tmp, out)
    return out


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- geometry helpers
def in_window(pt, win):
    return win[0] <= pt[0] <= win[1] and win[2] <= pt[1] <= win[3]


def rep_point(r):
    if r["ins"]:
        return r["ins"]
    v = r["verts"]
    return (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) if v else (1e18, 1e18)


def case_of(r):
    pt = rep_point(r)
    hits = [c for c, d in CASES.items() if in_window(pt, d["window"])]
    return hits[0] if len(hits) == 1 else None


def frame(p, q):
    L = math.dist(p, q)
    u = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
    return L, u, (-u[1], u[0])


def tile_extents(verts, p, u, n):
    ax = [(v[0] - p[0]) * u[0] + (v[1] - p[1]) * u[1] for v in verts]
    la = [(v[0] - p[0]) * n[0] + (v[1] - p[1]) * n[1] for v in verts]
    return min(ax), max(ax), min(la), max(la)


def near(a, b, tol=TOL):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ---------------------------------------------------------------- analysis
def analyse(diag, census, baseline_census):
    rows = census["rows"]
    fittings_by_handle = {f["handle"]: f for f in diag["fittings"]}
    result = dict(joints=[], accounting=dict(), checks=[], cases={})
    consumed: set[str] = set()
    expected_missing: list[dict] = []
    unexpected: list[dict] = []
    duplicates: list[dict] = []
    matched_by_case = defaultdict(Counter)
    entity_class: dict[str, str] = {}

    # tiles / paths / inserts by case
    by_case = defaultdict(list)
    for r in rows:
        by_case[case_of(r)].append(r)

    for cid, cdef in CASES.items():
        nodes, edges = topology(cdef["paths"])
        ents = by_case[cid]
        node_idx = {n: i + 1 for i, n in enumerate(sorted(nodes))}
        # --- designed PATH entities
        paths = [e for e in ents if e["layer"] == "SCADA-TRAY-PATH"]
        for dp in cdef["paths"]:
            hit = [e for e in paths if len(e["verts"]) == len(dp) and all(near(a, b, 1e-3) for a, b in zip(e["verts"], dp))]
            if len(hit) == 1:
                entity_class[hit[0]["handle"]] = "PATH matched"
                matched_by_case[cid]["PATH"] += 1
            else:
                expected_missing.append(dict(case=cid, what="PATH", detail=str(dp), found=len(hit)))
        # --- fittings expected at designed nodes
        fit_rows = [e for e in ents if e["type"] == "INSERT"]
        fit_at = {}
        for n, v in nodes.items():
            if v["type"] not in ("ELBOW", "TEE", "CROSS"):
                continue
            cands = [f for f in diag["fittings"] if f["junction"] and math.dist((f["junction"]["junction_x"], f["junction"]["junction_y"]), n) <= 1e-3]
            if len(cands) == 1 and cands[0]["fitting_type"] == v["type"]:
                fit_at[n] = cands[0]
                entity_class[cands[0]["handle"]] = "FITTING matched"
                matched_by_case[cid]["FITTING"] += 1
            else:
                expected_missing.append(dict(case=cid, what="FITTING " + v["type"], detail=str(n), found=len(cands)))
        # --- expected Straight tiles per edge, from opening distances (block geometry) -> consume census tiles
        tiles = [e for e in ents if e["type"] == "LWPOLYLINE" and "CTR_GEN:STRAIGHT" in e["tag"]]
        edge_info = []
        for (p, q, L) in edges:
            _, u, nrm = frame(p, q)
            dir_pq = direction(q[0] - p[0], q[1] - p[1])
            d_p = d_q = 0.0
            for end, dd, arm in ((p, "p", dir_pq), (q, "q", OPP[dir_pq])):
                f = fit_at.get(end)
                if f:
                    c = next((c for c in f["connections"] if c["direction"] == arm), None)
                    val = c["opening_distance_from_junction_mm"] if c and c["opening_distance_from_junction_mm"] is not None else None
                    if val is None:
                        expected_missing.append(dict(case=cid, what="opening distance", detail="%s %s" % (f["handle"], arm), found=0))
                        val = 0.0
                    if dd == "p":
                        d_p = val
                    else:
                        d_q = val
            span = (d_p, L - d_q)
            exp = []
            if span[1] - span[0] > TOL:
                exp += [("rail", span[0], span[1], RAIL_INNER, RAIL_OUTER), ("rail", span[0], span[1], -RAIL_OUTER, -RAIL_INNER)]
                for k in range(int((span[1] - span[0] + 1e-4) / RUNG_SP)):
                    c0 = span[0] + RUNG_FIRST + RUNG_SP * k
                    exp.append(("rung", c0 - RUNG_W / 2, c0 + RUNG_W / 2, -RUNG_HALF, RUNG_HALF))
            edge_info.append(dict(p=p, q=q, L=L, u=u, n=nrm, dir_pq=dir_pq, span=span, exp=exp, d_p=d_p, d_q=d_q, got=[]))
        owned = defaultdict(list)
        for t in tiles:
            owner = None
            for k, ei in enumerate(edge_info):
                a0, a1, l0, l1 = tile_extents(t["verts"], ei["p"], ei["u"], ei["n"])
                if -1.0 <= (a0 + a1) / 2 <= ei["L"] + 1.0 and abs((l0 + l1) / 2) <= RAIL_OUTER + 10.0:
                    owner = k
                    owned[k].append((t, (a0, a1, l0, l1)))
                    break
            if owner is None:
                unexpected.append(dict(case=cid, handle=t["handle"], why="Straight tile outside every designed edge"))
                entity_class[t["handle"]] = "UNEXPECTED straight tile"
        for k, ei in enumerate(edge_info):
            # the Router anchors the rung pattern at the START of its own segment: accept the anchor (p-end or q-end)
            # that explains the tiles of this edge; rails are symmetric
            cands = []
            for anchor in ("p", "q"):
                exp = [e for e in ei["exp"] if e[0] == "rail"]
                n_r = int((ei["span"][1] - ei["span"][0] + 1e-4) / RUNG_SP) if ei["span"][1] - ei["span"][0] > TOL else 0
                for j in range(n_r):
                    c0 = ei["span"][0] + RUNG_FIRST + RUNG_SP * j if anchor == "p" else ei["span"][1] - RUNG_FIRST - RUNG_SP * j
                    exp.append(("rung", c0 - RUNG_W / 2, c0 + RUNG_W / 2, -RUNG_HALF, RUNG_HALF))
                score = sum(1 for (_, ext) in owned[k] if any(near(e[1:], ext) for e in exp))
                cands.append((score, anchor, exp))
            score, anchor, exp = max(cands, key=lambda c: c[0])
            ei["exp"], ei["anchor"] = exp, anchor
            for t, ext in owned[k]:
                slot = next((i for i, e in enumerate(ei["exp"]) if i not in [g[0] for g in ei["got"]] and near(e[1:], ext)), None)
                if slot is not None:
                    ei["got"].append((slot, t["handle"], ext))
                    entity_class[t["handle"]] = "STRAIGHT %s matched" % ei["exp"][slot][0]
                    matched_by_case[cid]["STRAIGHT_" + ei["exp"][slot][0].upper()] += 1
                elif any(near(g[2], ext) for g in ei["got"]):
                    duplicates.append(dict(case=cid, handle=t["handle"], why="duplicate of an already matched tile"))
                    entity_class[t["handle"]] = "DUPLICATE straight tile"
                else:
                    unexpected.append(dict(case=cid, handle=t["handle"], why="tile does not match any expected rail/rung extents", extents=[round(x, 4) for x in ext]))
                    entity_class[t["handle"]] = "UNEXPECTED straight tile"
        for ei in edge_info:
            got = {g[0] for g in ei["got"]}
            for i, e in enumerate(ei["exp"]):
                if i not in got:
                    expected_missing.append(dict(case=cid, what="Straight " + e[0], detail="edge %s->%s extents %s" % (ei["p"], ei["q"], [round(x, 3) for x in e[1:]]), found=0))
        # --- joints
        for n, v in sorted(nodes.items()):
            if v["type"] not in ("ELBOW", "TEE", "CROSS"):
                continue
            f = fit_at.get(n)
            for arm in v["dirs"]:
                jid = "%s/N%d/%s" % (cid, node_idx[n], arm)
                row = dict(case_id=cid, joint_id=jid, junction_type=v["type"], orientation="+".join(v["dirs"]), node=list(n),
                           fitting_handle=f["handle"] if f else None, block=f["raw_block_name"] if f else None)
                if not f:
                    row.update(status="FAIL", reason="no fitting at designed junction")
                    result["joints"].append(row)
                    continue
                c = next((c for c in f["connections"] if c["direction"] == arm), None)
                ei = next(e for e in edge_info if (e["p"] == n and e["dir_pq"] == arm) or (e["q"] == n and OPP[e["dir_pq"]] == arm))
                # independent Straight start measured from the census tiles of this edge end
                rails = [g for g in ei["got"] if ei["exp"][g[0]][0] == "rail"]
                if rails:
                    start = min(g[2][0] for g in rails) if ei["p"] == n else ei["L"] - max(g[2][1] for g in rails)
                else:
                    start = None
                u_arm = UNIT[arm]
                derived = f["derived_joint_wcs"]
                zone = [e["handle"] for e in ents if any(math.dist(v2, n) <= ZONE for v2 in (e["verts"] or [e["ins"]]))]
                row.update(
                    expected_point=c["expected"][:2] if c and c["expected"] else None,
                    actual_point=c["actual"][:2] if c and c["actual"] else None,
                    gap_mm=max(0.0, -c["axial_error_mm"]) if c and c["axial_error_mm"] is not None else None,
                    overlap_mm=max(0.0, c["axial_error_mm"]) if c and c["axial_error_mm"] is not None else None,
                    axial_residual_mm=c["axial_error_mm"] if c else None,
                    lateral_error_mm=c["lateral_error_mm"] if c else None,
                    rail_center_differences_mm=c["rail_center_differences_mm"] if c else None,
                    opening_distance_mm=c["opening_distance_from_junction_mm"] if c else None,
                    straight_start_diag_mm=c["straight_start_distance_from_junction_mm"] if c else None,
                    straight_start_census_mm=start,
                    derived_joint_wcs=derived, designed_node=list(n),
                    candidate_entity_count=len(zone),
                    matched_entity_handles=[f["handle"]] + [g[1] for g in rails if (g[2][0] if ei["p"] == n else ei["L"] - g[2][1]) <= (start or 0) + TOL])
                ok_c = c is not None and c["status"] == "EXACT"
                row["centerline_status"] = "PASS" if (ok_c and abs(c["lateral_error_mm"]) <= TOL and
                                                      all(abs(d) <= TOL for d in (c["rail_center_differences_mm"] or [1e9]))) else "FAIL"
                row["insert_status"] = "PASS" if (derived and near(derived, n, TOL) and f["translation_fit"] and f["translation_fit"]["magnitude_mm"] <= TOL) else "FAIL"
                row["trim_status"] = "PASS" if (start is not None and c and abs(start - c["opening_distance_from_junction_mm"]) <= TOL
                                                and abs(start - c["straight_start_distance_from_junction_mm"]) <= TOL) else "FAIL"
                row["gap_overlap_status"] = "PASS" if (c and row["gap_mm"] <= TOL and row["overlap_mm"] <= TOL) else "FAIL"
                row["status"] = "PASS" if all(row[k] == "PASS" for k in ("centerline_status", "insert_status", "trim_status", "gap_overlap_status")) else "FAIL"
                result["joints"].append(row)
        result["cases"][cid] = dict(rung_anchors=dict(Counter(e.get("anchor", "-") for e in edge_info)), note=cdef["note"], window=cdef["window"], designed_nodes={str(k): v for k, v in nodes.items()},
                                    entities=len(ents), matched=dict(matched_by_case[cid]))

    # ---- global accounting
    census_types = Counter(r["type"] for r in rows)
    router_gen = [r for r in rows if "CTR_GEN" in r["tag"]]
    cls_counts = Counter(entity_class.get(r["handle"], "UNCLASSIFIED") for r in rows)
    unclassified = [r for r in rows if r["handle"] not in entity_class]
    for r in unclassified:
        unexpected.append(dict(case=case_of(r), handle=r["handle"], why="entity %s on layer %s matches nothing designed" % (r["type"], r["layer"])))
    result["accounting"] = dict(
        drawing_total_entities=len(rows), ssget_count=census["ssget_count"], by_type=dict(census_types),
        by_layer=dict(Counter(r["layer"] for r in rows)), by_layout=dict(Counter(r["layout"] for r in rows)), router_generated_entities=len(router_gen),
        router_generated_by_type=dict(Counter(r["type"] for r in router_gen)),
        user_path_entities=sum(1 for r in rows if r["layer"] == "SCADA-TRAY-PATH"),
        entities_outside_every_case_window=sum(1 for r in rows if case_of(r) is None),
        per_case={c: dict(entities=v["entities"], matched=v["matched"]) for c, v in result["cases"].items()},
        ladder_observation=dict(
            rungs_matched=cls_counts.get("STRAIGHT rung matched", 0), rung_lateral_half_mm=RUNG_HALF, rail_inner_edge_mm=RAIL_INNER,
            rung_end_to_rail_gap_mm=RAIL_INNER - RUNG_HALF,
            note="rungs follow the Router source rule (half length = width/2 - thickness) but the rails are centred on +-width/2, so every rung stops short of both rail inner edges; Straight-internal observation, not a joint error"),
        classification=dict(cls_counts), matched_total=sum(v for k, v in cls_counts.items() if "matched" in k),
        unmatched_total=len(unexpected), duplicates=len(duplicates),
        unexpected=unexpected, duplicate_entities=duplicates, expected_but_missing=expected_missing)

    # ---- item 8: Tee / Cross unchanged versus the pre-Elbow-fix Router
    def sig(r):
        v = tuple(tuple(round(c, 5) for c in p) for p in r["verts"])
        i = tuple(round(c, 5) for c in (r["ins"] + (r["rot"], r["scale"]))) if r["ins"] else None
        return (r["type"], r["layer"], r["name"], r["tag"], v, i)

    iso = [c for c in CASES if c.startswith(("B", "C"))]
    cmp = {}
    for cid in iso:
        a = Counter(sig(r) for r in rows if case_of(r) == cid)
        b = Counter(sig(r) for r in baseline_census["rows"] if case_of(r) == cid)
        cmp[cid] = dict(entities_now=sum(a.values()), entities_baseline=sum(b.values()), identical=(a == b and len(a) > 0))
    result["tee_cross_regression"] = cmp
    return result


def write_outputs(res, diag, info, extra):
    EVID.mkdir(exist_ok=True)
    (EVID / "joints.json").write_text(json.dumps(res["joints"], indent=1), encoding="utf-8")
    cols = ["case_id", "joint_id", "junction_type", "orientation", "fitting_handle", "expected_point", "actual_point", "gap_mm", "overlap_mm",
            "axial_residual_mm", "lateral_error_mm", "centerline_status", "insert_status", "trim_status", "gap_overlap_status",
            "candidate_entity_count", "matched_entity_handles", "status"]
    with open(EVID / "joints.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for j in res["joints"]:
            w.writerow([json.dumps(j.get(c)) if isinstance(j.get(c), (list, dict)) else j.get(c) for c in cols])
    (EVID / "entity_accounting.json").write_text(json.dumps(res["accounting"], indent=1), encoding="utf-8")
    (EVID / "diagnostics_all.json").write_text(json.dumps(diag, indent=1), encoding="utf-8")
    (EVID / "summary.json").write_text(json.dumps(dict(
        dwg=str(DWG), dwg_sha256_before=info["source_sha_before"], dwg_sha256_after=info["source_sha_after"],
        joints_total=len(res["joints"]), joints_pass=sum(j["status"] == "PASS" for j in res["joints"]),
        joints_fail=[j["joint_id"] for j in res["joints"] if j["status"] != "PASS"],
        tee_cross_regression=res["tee_cross_regression"], **extra), indent=1), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--rebuild" in sys.argv or not DWG.exists():
        build_drawing.build(build_drawing.ROUTER, DWG)
    work = Path(tempfile.mkdtemp(prefix="acc_run_"))
    diag, census, info = run_diagnostics_and_census(DWG, work)
    # baseline: the Router as of the parent of the Elbow-config commit (same cases, old Elbow values)
    old = subprocess.run(["git", "-C", r"D:\github\ezdxf\scada-v2-block-integration", "show", "5669d5a^:router/cable_tray_router.lsp"],
                         capture_output=True, check=True).stdout.decode("utf-8", "replace")
    base_dwg = build_to_scratch(old, "baseline_pre_elbow_fix")
    _, base_census, _ = run_diagnostics_and_census(base_dwg, Path(tempfile.mkdtemp(prefix="acc_runb_")))
    res = analyse(diag, census, base_census)
    reg = subprocess.run([sys.executable, str(ROUTER_DIR / "tools" / "run_tests.py")], cwd=str(ROUTER_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"RESULT: (\d+) passed, (\d+) failed", reg.stdout)
    extra = dict(router_regression=dict(passed=int(m.group(1)), failed=int(m.group(2))) if m else "UNPARSEABLE",
                 router_sha=hashlib.sha256((ROUTER_DIR / "cable_tray_router.lsp").read_bytes()).hexdigest(),
                 diagnostics_items_9_10="PENDING HUMAN GUI", width_scope="%d mm (this run only)" % WIDTH)
    write_outputs(res, diag, info, extra)
    acc = res["accounting"]
    print("DWG", DWG, "sha256 before/after", info["source_sha_before"][:16], info["source_sha_after"][:16])
    print("joints: %d total, %d PASS" % (len(res["joints"]), sum(j["status"] == "PASS" for j in res["joints"])))
    for j in res["joints"]:
        print("  %-22s %-5s %-8s start(census)=%s open=%s gap=%s ovl=%s lat=%s -> %s [%s|%s|%s|%s]" % (
            j["joint_id"], j["junction_type"], j["orientation"], None if j.get("straight_start_census_mm") is None else round(j["straight_start_census_mm"], 4),
            None if j.get("opening_distance_mm") is None else round(j["opening_distance_mm"], 4), j.get("gap_mm"), j.get("overlap_mm"),
            None if j.get("lateral_error_mm") is None else round(j["lateral_error_mm"], 6), j["status"],
            j.get("centerline_status"), j.get("insert_status"), j.get("trim_status"), j.get("gap_overlap_status")))
    print("accounting:", {k: acc[k] for k in ("drawing_total_entities", "ssget_count", "router_generated_entities", "user_path_entities", "matched_total", "unmatched_total", "duplicates")})
    print("by_type", acc["by_type"], "classification", acc["classification"])
    print("unexpected", acc["unexpected"][:5], "missing", acc["expected_but_missing"][:5])
    print("tee/cross regression", res["tee_cross_regression"])
    print("router regression", extra["router_regression"])


if __name__ == "__main__":
    main()
