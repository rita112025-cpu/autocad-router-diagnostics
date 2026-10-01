"""Shared L2 helper: run the tool + scene harness inside accoreconsole ONCE per test session.

L2 = real AutoCAD engine (accoreconsole), disposable blank drawing, known-answer scenes.
Skips (never silently passes) when accoreconsole.exe is not installed.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import accore_run  # noqa: E402

SCENES = [
    "line-path", "lw-multi", "elbow-r0", "elbow-r1", "elbow-r2", "elbow-r3", "basic-elbow",
    "tee-r0", "tee-r3", "cross", "mixed-paths", "profile-mismatch", "no-xdata", "no-path",
    "multi-candidates", "escape", "rot-error", "takeoff-error", "offset-error", "no-fitting",
    "topology-mismatch", "readonly", "unsupported-path-entity", "extrusion-insert", "xdata-tag-fitting",
    "future-profile", "not-a-fitting", "curved-r1", "curved-r3-shifted-pivot",
    "curved-router-assumption", "curved-takeoff-at-tangent", "curved-decoy", "curved-rot-error",
    "stacked-variants", "no-caps", "short-segment", "stacked-unpaired",
]
_cache: dict = {}


def engine_available() -> bool:
    return os.path.exists(accore_run.ACCORE)


def run_all(scenes=None) -> Path:
    """Run every scene once; returns the output root.  Cached per process."""
    scenes = scenes or SCENES
    key = tuple(scenes)
    if key in _cache:
        return _cache[key]
    work = Path(tempfile.mkdtemp(prefix="ctrdiag_l2_"))
    root = work / "out"
    root.mkdir()
    cmds = [f'(t:run-scene "{s}" "{root.as_posix()}/")' for s in scenes]
    log, info = accore_run.run(
        [REPO / "autocad_router_diagnostics.lsp", REPO / "tests" / "harness" / "scenes.lsp"],
        cmds, work / "engine", timeout=900)
    (root / "console.log").write_text(log, encoding="utf-8")
    _cache[key] = root
    return root


def latest_json(root: Path, scene: str, mode: str = "all") -> dict:
    files = sorted(glob.glob(str(root / scene / mode / "*.json")))
    if not files:
        raise FileNotFoundError(f"no JSON for scene={scene} mode={mode}")
    with open(files[-1], "r", encoding="utf-8") as f:
        return json.load(f)


def files_of(root: Path, scene: str, mode: str = "all") -> dict:
    d = root / scene / mode
    return {p.suffix: p for p in sorted(d.glob("*"))}


def console(root: Path) -> str:
    return (root / "console.log").read_text(encoding="utf-8")


def errors(root: Path) -> list[str]:
    return re.findall(r"^(?:SCENE_ERROR|RUN_ERROR).*$", console(root), flags=re.M)
