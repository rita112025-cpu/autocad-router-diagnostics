"""Build the SCADA_V2 @ 300 mm acceptance drawing with the committed Router (read-only use of the Router source).

A blank scratch drawing is created in accoreconsole, the PATH centre lines of every case are made with the Router's
own `ctr-make-path`, `CTU` generates Straights + fittings, and the result is saved as a NEW DWG (SAVEAS).
No existing drawing is opened or overwritten.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(HERE))
import accore_run  # noqa: E402
from cases import CASES, PROFILE, WIDTH  # noqa: E402

ROUTER = Path(r"D:\github\ezdxf\scada-v2-block-integration\router\cable_tray_router.lsp")


def build(router: Path, out_dwg: Path) -> str:
    cmds = ["(ctr-ensure-layers)"]
    for case in CASES.values():
        for path in case["paths"]:
            pts = " ".join("(list %.4f %.4f)" % p for p in path)
            cmds.append('(ctr-make-path (list %s) %.1f "%s")' % (pts, WIDTH, PROFILE))
    cmds.append("(c:CTU)")
    cmds.append('(princ (strcat (chr 10) "ENTITY_COUNT_AFTER_CTU=" (itoa (sslength (ssget "_X")))))')
    out_dwg.parent.mkdir(parents=True, exist_ok=True)
    if out_dwg.exists():
        out_dwg.unlink()
    cmds += ["_.SAVEAS", "2018", out_dwg.as_posix()]
    work = Path(tempfile.mkdtemp(prefix="acc_build_"))
    log, info = accore_run.run([router], cmds, work, timeout=900)
    (work / "build.log").write_text(log, encoding="utf-8")
    return log


if __name__ == "__main__":
    target = Path(sys.argv[1])
    log = build(ROUTER, target)
    sys.stdout.reconfigure(encoding="utf-8")
    for line in log.splitlines():
        if line.startswith(("[CTR]", "ENTITY_COUNT", "RUNG")) and "NEEDS" not in line:
            print(line[:200])
    print("saved:", target.exists(), target.stat().st_size if target.exists() else 0)
