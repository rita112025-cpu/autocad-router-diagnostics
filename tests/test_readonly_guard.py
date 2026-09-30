"""L1 (pure static): the AutoLISP tool must be structurally incapable of modifying a drawing.

Comments and string contents are stripped first, so words in documentation never count.
Any use of a forbidden function, or of an unknown vla-/vlax- function, is a FAIL.
"""
import re
import unittest
from pathlib import Path

LSP = Path(__file__).resolve().parents[1] / "autocad_router_diagnostics.lsp"

FORBIDDEN_EXACT = {
    "entmod", "entdel", "entmake", "entmakex", "entupd", "command", "command-s", "vl-cmdf",
    "setvar", "regapp", "ssdel", "dictadd", "dictremove", "dictrename", "dictnext",
    "namedobjdict", "vl-file-delete", "vl-file-rename", "vl-file-copy", "load", "startapp",
    "vl-registry-write", "vl-registry-delete", "setenv", "xdroom", "xdsize", "setview",
    "initcommandversion", "vl-directory-files-delete", "acad-push-dbmod", "acad-pop-dbmod",
    "vlr-object-reactor", "vlr-command-reactor", "vlr-acdb-reactor", "vlr-editor-reactor",
    "menucmd", "grdraw", "redraw", "regen", "save", "qsave", "saveas", "erase", "move", "rotate",
    "scale", "explode", "insert", "ct", "ctu", "ctray",
}
FORBIDDEN_PREFIXES = ("vla-put", "vla-delete", "vla-erase", "vla-move", "vla-rotate", "vla-scale",
                      "vla-copy", "vla-mirror", "vla-add", "vla-save", "vla-close", "vla-explode",
                      "vla-update", "vla-regen", "vla-set", "vla-offset", "vla-array", "vla-transformby",
                      "vlax-put", "vlax-invoke", "vlax-set", "vlax-make", "vlax-import", "vlax-release",
                      "vlax-3d-point")
ALLOWED_VLA = {"vla-getboundingbox"}
ALLOWED_TOP_LEVEL = ("defun", "setq", "vl-load-com", "princ")


def strip(source: str) -> str:
    out, i, n = [], 0, len(source)
    while i < n:
        c = source[i]
        if c == '"':
            j = i + 1
            while j < n and source[j] != '"':
                j += 2 if source[j] == "\\" else 1
            out.append('""')
            i = j + 1
        elif c == ";":
            while i < n and source[i] != "\n":
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def symbols(code: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[^\s()'\"]+", code)]


def top_level_forms(code: str) -> list[str]:
    forms, depth, start = [], 0, None
    for i, c in enumerate(code):
        if c == "(":
            if depth == 0:
                start = i
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0 and start is not None:
                forms.append(code[start:i + 1])
                start = None
    assert depth == 0, "unbalanced parentheses"
    return forms


class ReadOnlyGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = LSP.read_text(encoding="utf-8")
        cls.code = strip(cls.raw)
        cls.syms = symbols(cls.code)

    def test_no_forbidden_function(self):
        hits = sorted({s for s in self.syms if s in FORBIDDEN_EXACT})
        self.assertEqual(hits, [], "forbidden (drawing-modifying) functions used: %s" % hits)

    def test_no_forbidden_prefix_and_unknown_vla(self):
        bad = sorted({s for s in self.syms if s.startswith(FORBIDDEN_PREFIXES)})
        self.assertEqual(bad, [], "forbidden ActiveX mutators: %s" % bad)
        vla = sorted({s for s in self.syms if s.startswith("vla-") and s not in ALLOWED_VLA})
        self.assertEqual(vla, [], "unreviewed vla- functions (add to ALLOWED_VLA only if read-only): %s" % vla)

    def test_vlax_functions_are_read_only_whitelist(self):
        allowed = {"vlax-ename->vla-object", "vlax-get-property", "vlax-safearray->list", "vlax-variant-value",
                   "vlax-curve-getstartparam", "vlax-curve-getendparam", "vlax-curve-getpointatparam"}
        vlax = {s for s in self.syms if s.startswith("vlax-")}
        self.assertEqual(sorted(vlax - allowed), [])

    def test_only_one_open_call_and_it_is_write_to_external_file(self):
        opens = re.findall(r"\(open\s+[^)]*\)", self.code)
        self.assertEqual(len(opens), 1, opens)
        self.assertRegex(self.raw, r'\(open path "w" "utf8"\)')

    def test_top_level_forms_do_not_scan_on_load(self):
        for form in top_level_forms(self.code):
            head = re.match(r"\(\s*([^\s()]+)", form).group(1).lower()
            self.assertIn(head, ALLOWED_TOP_LEVEL, "top-level form runs code at load: " + form[:60])
            if head == "princ":
                self.assertNotIn("ssget", form.lower())
        # nothing that scans/reads the drawing may be a bare top-level call
        for form in top_level_forms(self.code):
            head = re.match(r"\(\s*([^\s()]+)", form).group(1).lower()
            if head == "setq":
                self.assertNotRegex(form.lower(), r"\(ssget|\(entget|\(entsel|\(ard:run[\s)]|\(ard:scan|\(ard:guarded")

    def test_exactly_the_three_commands(self):
        cmds = sorted(set(re.findall(r"\(defun\s+c:(\w+)", self.code, flags=re.I)))
        self.assertEqual([c.upper() for c in cmds], ["CTRDIAG", "CTRDIAGALL", "CTRDIAGEXPORT"])

    def test_commands_install_error_handler(self):
        for name in ("CTRDIAG", "CTRDIAGALL", "CTRDIAGEXPORT"):
            m = re.search(r"\(defun c:%s \(([^)]*)\)" % name, self.raw)
            self.assertIsNotNone(m, name)
            self.assertIn("*error*", m.group(1))
            body = self.raw[m.end(): self.raw.index("(defun c:", m.end()) if "(defun c:" in self.raw[m.end():] else len(self.raw)]
            self.assertIn("(defun *error*", body)
            self.assertIn("ard:close-all", body)

    def test_no_backslash_characters(self):
        self.assertNotIn("\\", self.raw)

    def test_ascii_only(self):
        self.raw.encode("ascii")

    def test_harness_is_not_referenced(self):
        self.assertNotIn("harness", self.raw.lower())
        self.assertNotIn("t:run-scene", self.raw)

    def test_static_scan_detects_a_violation(self):
        """Self-test of the guard: a mutating snippet must be caught."""
        snippet = symbols(strip('(defun x () (entmod (entget e)) ; entdel in a comment\n (princ "entmake"))'))
        self.assertIn("entmod", snippet)
        self.assertNotIn("entdel", snippet)
        self.assertNotIn("entmake", snippet)


if __name__ == "__main__":
    unittest.main()
