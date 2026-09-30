#!/usr/bin/env python3
"""Analyse a CTRDIAG / CTRDIAGALL / CTRDIAGEXPORT JSON report (standard library only).

    python analyze_diagnostics.py output\\ctrdiag_YYYYMMDD_HHMMSS_all.json
    python analyze_diagnostics.py report.json --json      # machine-readable result
    python analyze_diagnostics.py report.json --strict    # exit 1 when any FAIL exists

The analyser never needs AutoCAD.  It only reads the JSON written by
autocad_router_diagnostics.lsp (schema_version 1.0).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

FAIL_CODES_PROFILE = ("FITTING_PROFILE_MISMATCH", "PATH_PROFILE_MISMATCH")
BLOCK_CONSISTENCY_TOL_MM = 1e-3      # block-space vectors closer than this are "the same"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _round(v: Any, n: int = 6) -> Any:
    return round(v, n) if isinstance(v, float) else v


def load(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or "fittings" not in data or "paths" not in data:
        raise ValueError("not a Router diagnostics report (missing fittings/paths)")
    return data


def _issues(obj: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in (obj.get("issues") or []) if isinstance(i, dict)]


def _profile_family(name: str | None) -> str:
    """BASIC / V2 / DEFAULT / other, from a profile name such as SCADA_V2."""
    if not name:
        return "UNKNOWN"
    upper = name.upper()
    if upper.endswith("_V2") or upper == "V2":
        return "V2"
    if "BASIC" in upper:
        return "BASIC"
    if upper == "DEFAULT":
        return "DEFAULT"
    return name


def fitting_row(f: dict[str, Any]) -> dict[str, Any]:
    junction = f.get("junction") or {}
    connected = [c.get("handle") for c in f.get("connected_path_candidates", [])
                 if c.get("touches_junction") or c.get("relation") in ("exact", "near")]
    translation = f.get("translation_fit") or {}
    return OrderedDict([
        ("handle", f.get("handle")),
        ("block", f.get("raw_block_name")),
        ("fitting_type", f.get("fitting_type")),
        ("profile", f.get("profile")),
        ("position", [_round(f.get("insert_x")), _round(f.get("insert_y")), _round(f.get("insert_z"))]),
        ("rotation_deg", _round(f.get("rotation_deg"))),
        ("scale", [_round(f.get("scale_x")), _round(f.get("scale_y")), _round(f.get("scale_z"))]),
        ("junction", None if not junction else [_round(junction.get("junction_x")), _round(junction.get("junction_y"))]),
        ("directions", junction.get("directions")),
        ("classification", junction.get("classification")),
        ("connected_paths", connected),
        ("max_connection_error_mm", _round(f.get("max_connection_error_mm"))),
        ("translation_block_coords", None if not translation else [_round(v) for v in translation.get("in_block_coords", [])]),
        ("status", f.get("status")),
        ("issue_codes", [i.get("code") for i in _issues(f)]),
    ])


def consistency(fittings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-fitting checks.  A value that is identical across fittings of one block, whatever their
    rotation, is a *systematic* (configuration / block-definition) effect, not a per-instance error."""
    findings: list[dict[str, Any]] = []
    by_block: dict[str, list[dict[str, Any]]] = {}
    for f in fittings:
        if f.get("junction") and f.get("raw_block_name"):
            by_block.setdefault(f["raw_block_name"], []).append(f)
    for block, group in by_block.items():
        if len(group) < 2:
            continue
        # 1. where the PATH junction lies in block coordinates must not depend on rotation
        pts = [f.get("junction_in_block_coords") for f in group if f.get("junction_in_block_coords")]
        if pts:
            spread = max(max(abs(p[0] - pts[0][0]), abs(p[1] - pts[0][1])) for p in pts)
            findings.append(OrderedDict([
                ("check", "JUNCTION_IN_BLOCK_COORDS_CONSTANT"),
                ("block", block), ("fittings", [f["handle"] for f in group]),
                ("value", [_round(v) for v in pts[0]]), ("spread", _round(spread)),
                ("consistent", spread <= BLOCK_CONSISTENCY_TOL_MM),
                ("meaning", "constant across rotations => BASE_OFFSET is applied rotation-consistently; "
                            "a spread means a rotation-dependent placement error")]))
        # 2. the residual translation (block coords) shows whether an error is systematic
        trans = [f["translation_fit"]["in_block_coords"] for f in group
                 if f.get("translation_fit") and f["translation_fit"].get("magnitude_mm", 0) > 1.0]
        if len(trans) >= 2:
            spread = max(max(abs(t[0] - trans[0][0]), abs(t[1] - trans[0][1])) for t in trans)
            findings.append(OrderedDict([
                ("check", "TRANSLATION_IN_BLOCK_COORDS_CONSTANT"),
                ("block", block), ("fittings", [f["handle"] for f in group if f.get("translation_fit")]),
                ("value", [_round(v) for v in trans[0]]), ("spread", _round(spread)),
                ("consistent", spread <= BLOCK_CONSISTENCY_TOL_MM),
                ("meaning", "same block-space shift on fittings with different rotations => placement error is "
                            "in the block origin / BASE_OFFSET, not in the rotation mapping")]))
        # 3. rotation must be a pure function of the junction directions
        rot_by_dirs: dict[str, set] = {}
        for f in group:
            key = ",".join(f["junction"].get("directions") or [])
            rot_by_dirs.setdefault(key, set()).add(round((f.get("rotation_deg") or 0.0) % 360.0, 4))
        bad = {k: sorted(v) for k, v in rot_by_dirs.items() if len(v) > 1}
        findings.append(OrderedDict([
            ("check", "ROTATION_FUNCTION_OF_DIRECTIONS"), ("block", block),
            ("rotation_by_directions", {k: sorted(v) for k, v in rot_by_dirs.items()}),
            ("consistent", not bad),
            ("meaning", "same block + same junction directions must use the same rotation")]))
    return findings


def analyze(report: dict[str, Any]) -> dict[str, Any]:
    fittings, paths, junctions = (report.get(k) for k in ("fittings", "paths", "junctions"))
    fittings, paths, junctions = (v if v is not None else [] for v in (fittings, paths, junctions))
    if not all(isinstance(v, list) for v in (fittings, paths, junctions)):
        raise ValueError("fittings, paths and junctions must be arrays")

    by_type = Counter((f.get("fitting_type") or "UNKNOWN") for f in fittings)
    by_prefix = Counter((f.get("resolved_profile_prefix") or "(none)") for f in fittings)
    by_family = Counter(_profile_family(f.get("profile")) for f in fittings)
    path_profiles = Counter(_profile_family(p.get("profile")) for p in paths)

    profile_mismatch = []
    for f in fittings:
        codes = [i for i in _issues(f) if i.get("code") in FAIL_CODES_PROFILE]
        if codes:
            profile_mismatch.append(OrderedDict([
                ("fitting", f.get("handle")), ("block", f.get("raw_block_name")),
                ("fitting_profile", f.get("profile")),
                ("path_profiles", (f.get("junction") or {}).get("profiles")),
                ("details", [c.get("detail") for c in codes])]))
    path_profile_conflicts = []
    for j in junctions:
        if any(i.get("code") == "PATH_PROFILE_MISMATCH" for i in _issues(j)):
            path_profile_conflicts.append(OrderedDict([
                ("junction", [_round(j.get("junction_x")), _round(j.get("junction_y"))]),
                ("fittings", j.get("fitting_handles")),
                ("arms", [OrderedDict([("path", a.get("path_handle")), ("direction", a.get("direction")),
                                       ("profile", a.get("profile"))]) for a in (j.get("arms") or [])])]))

    ranked = sorted((f for f in fittings if _num(f.get("max_connection_error_mm")) is not None),
                    key=lambda f: -f["max_connection_error_mm"])
    largest = None
    if ranked:
        top = ranked[0]
        largest = OrderedDict([("handle", top.get("handle")), ("block", top.get("raw_block_name")),
                               ("error_mm", _round(top["max_connection_error_mm"]))])

    problems = []
    for f in fittings:
        for i in _issues(f):
            problems.append(OrderedDict([("object", "FITTING"), ("handle", f.get("handle")),
                                         ("severity", i.get("severity")), ("code", i.get("code")),
                                         ("detail", i.get("detail"))]))
        if f.get("status") == "NOT_COMPUTABLE" and not _issues(f):
            problems.append(OrderedDict([("object", "FITTING"), ("handle", f.get("handle")),
                                         ("severity", "WARN"), ("code", "NOT_COMPUTABLE"), ("detail", "")]))
    for j in junctions:
        for i in _issues(j):
            problems.append(OrderedDict([
                ("object", "JUNCTION"),
                ("handle", "{:.3f},{:.3f}".format(j.get("junction_x", 0.0), j.get("junction_y", 0.0))),
                ("severity", i.get("severity")), ("code", i.get("code")), ("detail", i.get("detail"))]))
    for p in paths:
        if not p.get("profile_explicit", True):
            problems.append(OrderedDict([("object", "PATH"), ("handle", p.get("handle")),
                                         ("severity", "WARN"), ("code", "PATH_PROFILE_IMPLICIT"),
                                         ("detail", "no PROFILE= XDATA; Router treats it as DEFAULT / 300")]))
    for w in report.get("warnings") or []:
        problems.append(OrderedDict([("object", "REPORT"), ("handle", ""), ("severity", "WARN"),
                                     ("code", w.get("code")), ("detail", w.get("message"))]))
    order = {"FAIL": 0, "WARN": 1}
    problems.sort(key=lambda p: (order.get(p["severity"], 2), str(p["object"]), str(p["handle"])))

    return OrderedDict([
        ("drawing", report.get("drawing")), ("mode", report.get("mode")),
        ("timestamp", report.get("timestamp")),
        ("fitting_count", len(fittings)),
        ("fitting_types", {k: by_type[k] for k in sorted(by_type)}),
        ("fitting_profile_prefixes", {k: by_prefix[k] for k in sorted(by_prefix)}),
        ("fitting_profile_families", {k: by_family[k] for k in sorted(by_family)}),
        ("path_count", len(paths)),
        ("path_profile_families", {k: path_profiles[k] for k in sorted(path_profiles)}),
        ("profile_mismatch", profile_mismatch),
        ("path_profile_conflicts", path_profile_conflicts),
        ("largest_connection_error", largest),
        ("worst_fittings", [fitting_row(f) for f in ranked[:5]]),
        ("status_counts", dict(Counter(f.get("status") or "DATA" for f in fittings))),
        ("problems", problems),
        ("fittings", [fitting_row(f) for f in fittings]),
        ("consistency", consistency(fittings)),
    ])


def format_text(result: dict[str, Any]) -> str:
    out: list[str] = []
    add = out.append
    add("Router diagnostics analysis  drawing={}  mode={}  timestamp={}".format(
        result["drawing"], result["mode"], result["timestamp"]))
    add("")
    add("1. fittings: {}".format(result["fitting_count"]))
    add("2. by type: " + (", ".join("{}={}".format(k, v) for k, v in result["fitting_types"].items()) or "-"))
    add("3. by profile: " + (", ".join("{}={}".format(k, v) for k, v in result["fitting_profile_families"].items()) or "-")
        + "   (block prefixes: " + (", ".join("{}={}".format(k, v) for k, v in result["fitting_profile_prefixes"].items()) or "-") + ")")
    add("4. PATHs: {}   by profile: {}".format(
        result["path_count"], ", ".join("{}={}".format(k, v) for k, v in result["path_profile_families"].items()) or "-"))
    add("5. PROFILE_MISMATCH: {}".format(len(result["profile_mismatch"]) + len(result["path_profile_conflicts"])))
    for m in result["profile_mismatch"]:
        add("   fitting {} {} profile={} PATH profiles={}".format(m["fitting"], m["block"], m["fitting_profile"], m["path_profiles"]))
        for d in m["details"]:
            add("      " + str(d))
    for c in result["path_profile_conflicts"]:
        add("   junction {} arms: {}".format(c["junction"], ", ".join(
            "{}({}) {}".format(a["path"], a["direction"], a["profile"]) for a in c["arms"])))
    big = result["largest_connection_error"]
    add("6. largest connection error: " + ("none computable" if not big else
        "fitting {} {} = {} mm".format(big["handle"], big["block"], big["error_mm"])))
    add("   status: " + ", ".join("{}={}".format(k, v) for k, v in sorted(result["status_counts"].items())))
    add("")
    add("7. FAIL / WARN ({}):".format(len(result["problems"])))
    for p in result["problems"]:
        add("   [{}] {} {} {}: {}".format(p["severity"], p["object"], p["handle"], p["code"], p["detail"]))
    add("")
    add("8. fittings:")
    for r in result["fittings"]:
        add("   {} {} {} [{}]".format(r["handle"], r["fitting_type"], r["block"], r["status"]))
        add("      position={}  rotation={}  scale={}".format(r["position"], r["rotation_deg"], r["scale"]))
        add("      junction={} {} {}  connected PATH={}  max geometry error={} mm".format(
            r["junction"], r["classification"], r["directions"], r["connected_paths"], r["max_connection_error_mm"]))
        if r["translation_block_coords"]:
            add("      residual translation in block coords={}".format(r["translation_block_coords"]))
    if result["consistency"]:
        add("")
        add("9. cross-fitting consistency:")
        for c in result["consistency"]:
            extra = {k: v for k, v in c.items() if k not in ("check", "block", "meaning")}
            add("   {} block={} -> {}".format(c["check"], c["block"], extra))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path, help="JSON written by CTRDIAG / CTRDIAGALL / CTRDIAGEXPORT")
    parser.add_argument("--json", action="store_true", help="print the analysis as JSON instead of text")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any FAIL is present")
    args = parser.parse_args(argv)
    try:
        report = load(args.report)
        result = analyze(report)
    except (OSError, ValueError) as error:
        print("analyze_diagnostics: {}".format(error), file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_text(result))
    if args.strict and any(p["severity"] == "FAIL" for p in result["problems"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
