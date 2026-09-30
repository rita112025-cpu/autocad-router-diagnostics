"""Run AutoLISP against a SCRATCH COPY of a drawing with accoreconsole (L2 engine).

The source drawing is never opened: it is copied first, the copy is opened, and the
script always ends with _QUIT Y (discard).  SECURELOAD blocks (load) from arbitrary
folders, so the LISP sources are inlined (comment-stripped) into the script.
Standard library only.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ACCORE = r"C:\Program Files\Autodesk\AutoCAD 2027\accoreconsole.exe"


def strip_lisp(src: str) -> str:
    """Remove ; comments and #| |# blocks, keep strings intact, drop blank lines."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif c == ";":
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("#|", i):
            i = src.index("|#", i) + 2
        else:
            out.append(c)
            i += 1
    lines = [ln.rstrip() for ln in "".join(out).splitlines()]
    return "\n".join(ln for ln in lines if ln.strip())


def decode_console(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data[:200]:
        return data.decode("utf-16-le", errors="replace")
    for enc in ("utf-8", "mbcs"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(lisp_files: list[Path], commands: list[str], workdir: Path,
        drawing: Path | None = None, timeout: int = 300) -> tuple[str, dict]:
    """Copy `drawing` (or start empty), inline `lisp_files`, run `commands`, discard.

    Returns (console_log, info).  info has 'source_sha_before/after' when a drawing is used.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    info: dict = {}
    args = [ACCORE]
    if drawing is not None:
        info["source_sha_before"] = sha256(drawing)
        copy = workdir / drawing.name          # keep the original file name so DWGNAME matches
        shutil.copyfile(drawing, copy)
        args += ["/i", str(copy)]
    parts = ["FILEDIA", "0"]
    for f in lisp_files:
        parts.append(strip_lisp(Path(f).read_text(encoding="utf-8")))
    parts += commands
    parts += ["_QUIT", "Y", ""]
    scr = workdir / "run.scr"
    scr.write_bytes("\n".join(parts).encode("mbcs", errors="replace"))
    args += ["/s", str(scr), "/l", "en-US"]
    proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                          cwd=str(workdir))
    log = decode_console(proc.stdout)
    (workdir / "console.log").write_text(log, encoding="utf-8")
    info["returncode"] = proc.returncode
    if drawing is not None:
        info["source_sha_after"] = sha256(drawing)
    return log, info
