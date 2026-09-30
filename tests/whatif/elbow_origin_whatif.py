"""WHAT-IF experiment (not a unit test, not part of the tool).

Question: is the systematic Elbow error explained by the block-origin translation the tool reports?
Method: in a SCRATCH COPY inside accoreconsole, move the failing Elbow INSERT by the negative of the
tool's own translation_fit, run the read-only tool again, and see what remains.  The original DWG is
never opened (copy first, discard on exit); entmod appears only in this experiment script, never in the tool.

    python tests/whatif/elbow_origin_whatif.py D:\TEST\TEST.dwg 514 output\ctrdiag_XXXX_all.json
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import accore_run  # noqa: E402


def main() -> int:
    drawing, handle, report = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    data = json.loads(report.read_text(encoding="utf-8"))
    fit = next(f for f in data["fittings"] if f["handle"] == handle)
    tx, ty = fit["translation_fit"]["dx"], fit["translation_fit"]["dy"]
    new_x, new_y = fit["insert_x"] - tx, fit["insert_y"] - ty
    out = Path(tempfile.mkdtemp(prefix="ctrdiag_whatif_"))
    lisp = (
        '(setq ard:out-dir "%s/")' % out.as_posix(),
        '(setq ard:run-note "WHAT-IF on a scratch copy: fitting %s moved by the negative of translation_fit")' % handle,
        '(setq e (handent "%s"))' % handle,
        '(setq ed (entget e))',
        '(entmod (subst (list 10 %r %r 0.0) (assoc 10 ed) ed))' % (new_x, new_y),
        '(ard:guarded "single" e "WHATIF")',
    )
    log, info = accore_run.run([REPO / "autocad_router_diagnostics.lsp"], list(lisp), out / "engine", drawing=drawing)
    if info["source_sha_before"] != info["source_sha_after"]:
        print("ORIGINAL CHANGED!", file=sys.stderr)
        return 1
    after = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))["fittings"][0]
    print("moved insert by (%.6f, %.6f) -> new insert (%.6f, %.6f)" % (-tx, -ty, new_x, new_y))
    print("status", after["status"], " translation magnitude %.6f mm" % after["translation_fit"]["magnitude_mm"])
    for c in after["connections"]:
        print("  arm %s  %s  error %.6f mm  axial %.6f  lateral %.6f  (straight end width %.3f, fitting opening %.3f)" % (
            c["direction"], c["status"], c["error_mm"], c["axial_error_mm"], c["lateral_error_mm"],
            c["straight_end_width_mm"], c["fitting_opening_width_mm"]))
    for p in after["translation_fit"]["per_arm"]:
        print("  residual arm %s: axial %.6f mm (= %.6f block units), lateral %.6f mm" % (
            p["direction"], p["axial_residual_mm"], p["axial_residual_mm"] / fit["scale_x"], p["lateral_residual_mm"]))
    print("original untouched:", info["source_sha_before"] == info["source_sha_after"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
