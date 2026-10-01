"""Compare two CTRDIAGALL JSON reports of the SAME acceptance drawing (e.g. before SAVE / after REOPEN).

    python acceptance/compare_reports.py before.json after.json
Exit 0 only if fittings, PATHs, Straights and every joint number are identical (1e-6) and counts match.
"""
import json
import sys
from pathlib import Path


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def fit_key(f):
    return (f["handle"], f["raw_block_name"], round(f["insert_x"], 6), round(f["insert_y"], 6), round(f["rotation_deg"], 6),
            round(f["scale_x"], 8), f["status"], tuple(round(c["error_mm"], 6) if c["error_mm"] is not None else None for c in f["connections"]))


def geom_key(o):
    return (o["handle"], tuple((round(v["x"], 6), round(v["y"], 6)) for v in o["vertices"]))


def main(a, b):
    ra, rb = load(a), load(b)
    problems = []
    for name, key in (("fittings", fit_key), ("paths", geom_key), ("generated_geometry", geom_key)):
        ka, kb = sorted(key(x) for x in ra[name]), sorted(key(x) for x in rb[name])
        if ka != kb:
            problems.append("%s differ: %d vs %d entries" % (name, len(ka), len(kb)))
    for k in ("fittings", "paths_in_drawing", "straights_in_drawing"):
        if ra["counts"][k] != rb["counts"][k]:
            problems.append("count %s: %s vs %s" % (k, ra["counts"][k], rb["counts"][k]))
    print("IDENTICAL" if not problems else "DIFFERENT\n  " + "\n  ".join(problems))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
