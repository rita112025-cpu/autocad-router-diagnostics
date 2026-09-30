"""Run the read-only diagnostics on a REAL drawing without opening the original.

The DWG is copied to a scratch folder, accoreconsole opens the copy, the tool runs, the copy is discarded
(_QUIT Y).  The original is hashed before and after to prove it was not touched.

    python tools/diagnose_real_drawing.py D:\TEST\TEST.dwg --fitting 514
    python tools/diagnose_real_drawing.py D:\TEST\TEST.dwg            # CTRDIAGALL + CTRDIAGEXPORT only

Outputs go to ./output (JSON + CSV + TXT per command).  Interactive CTRDIAG needs a GUI pick, so a handle is
given instead; the analysis code path is the same (ard:run "single" <ename>).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import accore_run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("drawing", type=Path)
    ap.add_argument("--fitting", action="append", default=[], help="handle of a fitting INSERT (repeatable)")
    ap.add_argument("--out", type=Path, default=REPO / "output")
    args = ap.parse_args()
    if not args.drawing.exists():
        print("no such drawing:", args.drawing, file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out.resolve().as_posix() + "/"
    note = "engine run on a scratch COPY of %s (the original is never opened)" % args.drawing.as_posix()
    cmds = ['(setq ard:out-dir "%s")' % out, '(setq ard:run-note "%s")' % note]
    for handle in args.fitting:
        cmds.append('(princ (strcat (chr 10) "== CTRDIAG handle %s"))' % handle)
        cmds.append('(ard:guarded "single" (handent "%s") "CTRDIAG")' % handle)
    cmds.append('(ard:guarded "all" nil "CTRDIAGALL")')
    cmds.append('(ard:guarded "export" nil "CTRDIAGEXPORT")')
    work = Path(tempfile.mkdtemp(prefix="ctrdiag_real_"))
    log, info = accore_run.run([REPO / "autocad_router_diagnostics.lsp"], cmds, work, drawing=args.drawing)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in log.splitlines():
        if line.startswith(("CTRDIAG", "FITTING", "  ", "JSON", "CSV", "TXT", "==")) and not line.startswith("(("):
            print(line)
    print("source sha256 before:", info["source_sha_before"])
    print("source sha256 after :", info["source_sha_after"])
    print("original untouched  :", info["source_sha_before"] == info["source_sha_after"])
    return 0 if info["source_sha_before"] == info["source_sha_after"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
