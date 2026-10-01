"""L1b: pure AutoLISP logic of the tool, executed by the real AutoCAD engine (accoreconsole)
WITHOUT any drawing entities: literal data in, printed value out.

  L1  pure logic      -> test_analyzer.py, test_readonly_guard.py (Python only) and this file (LISP, no scene)
  L2  AutoCAD engine  -> test_engine_scenes.py (entmake known-answer scenes, then the tool runs on them)
  L3  Human GUI       -> docs/L3_HUMAN_CHECKLIST.md (APPLOAD, entsel pick, ActiveX bbox / EffectiveName)
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import accore_run  # noqa: E402

BS, Q = "\\", '"'


def lisp_str(expr: str) -> str:
    # the LISP source must not contain backslashes, so expressions use (chr ..) only
    assert BS not in expr
    return expr


CASES = [
    # label, lisp expression yielding a string, expected
    ("jstr_specials", '(ard:jstr (strcat "a" (chr 34) "b" (chr 92) "c" (chr 10) "d" (chr 1) (chr 9) (chr 13)))',
     Q + 'a' + BS + Q + 'b' + BS + BS + 'c' + BS + 'n' + 'd' + BS + 'u0001' + BS + 't' + BS + 'r' + Q),
    ("jstr_unicode", '(ard:jstr (strcat "x" (chr 20013) (chr 25991)))', Q + "x中文" + Q),
    ("jstr_empty", '(ard:jstr "")', '""'),
    ("num_real", '(ard:num 8766.7604101634)', "8766.7604101634"),
    ("num_whole_real", '(ard:num 300.0)', "300"),
    ("num_int", '(ard:num 5)', "5"),
    ("num_tiny", '(ard:num 1.0e-12)', "0"),
    ("num_negative", '(ard:num -12.5)', "-12.5"),
    ("csv_plain", '(ard:csv-cell "plain")', "plain"),
    ("csv_comma", '(ard:csv-cell "a,b")', Q + "a,b" + Q),
    ("csv_quote", '(ard:csv-cell (strcat "x" (chr 34) "y"))', Q + "x" + Q + Q + "y" + Q),
    ("csv_newline", '(ard:csv-cell (strcat "l1" (chr 10) "l2"))', Q + "l1\nl2" + Q),
    ("csv_nil", '(ard:csv-cell nil)', ""),
    ("csv_number", '(ard:csv-cell 2.5)', "2.5"),
    ("csv_bool", '(strcat (ard:csv-cell T) "/" (ard:csv-cell (quote ARD_FALSE)))', "true/false"),
    ("csv_row", '(ard:csv-row (list "a" "b,c" nil 3))', 'a,"b,c",,3'),
    ("dir_E", '(ard:dir-label 5.0 0.0)', "E"),
    ("dir_N", '(ard:dir-label 0.0 5.0)', "N"),
    ("dir_W", '(ard:dir-label -5.0 0.0)', "W"),
    ("dir_W_tiny_neg_dy", '(ard:dir-label -1000.0 -1.0e-9)', "W"),
    ("dir_S", '(ard:dir-label 0.0 -5.0)', "S"),
    ("dir_other", '(ard:dir-label 1.0 1.0)', "OTHER"),
    ("dir_zero", '(ard:dir-label 0.0 0.0)', "OTHER"),
    ("cls_straight_ew", '(ard:classify (list "E" "W"))', "STRAIGHT"),
    ("cls_straight_ns", '(ard:classify (list "N" "S"))', "STRAIGHT"),
    ("cls_elbow", '(ard:classify (list "E" "N"))', "ELBOW"),
    ("cls_elbow2", '(ard:classify (list "W" "S"))', "ELBOW"),
    ("cls_tee", '(ard:classify (list "E" "W" "N"))', "TEE"),
    ("cls_cross", '(ard:classify (list "E" "W" "N" "S"))', "CROSS"),
    ("cls_end", '(ard:classify (list "E"))', "END"),
    ("cls_unknown_other", '(ard:classify (list "E" "OTHER"))', "UNKNOWN"),
    ("cls_empty", '(ard:classify nil)', "UNKNOWN"),
    ("dir_sort", '(vl-prin1-to-string (ard:dir-sort (list "S" "N" "W" "E")))', '("E" "W" "N" "S")'),
    ("cross_x", '(vl-princ-to-string (mapcar (function (lambda (v) (fix (+ 0.5 v)))) (ard:seg-cross (list (list 0.0 0.0) (list 10.0 10.0)) (list (list 0.0 10.0) (list 10.0 0.0)))))',
     "(5 5 0)"),
    ("cross_endpoint_touch_is_nil", '(vl-princ-to-string (ard:seg-cross (list (list 0.0 0.0) (list 10.0 0.0)) (list (list 5.0 0.0) (list 5.0 5.0))))', "nil"),
    ("cross_parallel_nil", '(vl-princ-to-string (ard:seg-cross (list (list 0.0 0.0) (list 10.0 0.0)) (list (list 0.0 1.0) (list 10.0 1.0))))', "nil"),
    ("seg_nearest_interior", '(rtos (car (ard:seg-nearest (list 5.0 3.0) (list 0.0 0.0) (list 10.0 0.0))) 2 4)', "3"),
    ("seg_nearest_beyond_end", '(rtos (car (ard:seg-nearest (list 13.0 4.0) (list 0.0 0.0) (list 10.0 0.0))) 2 4)', "5"),
    ("mat_compose", '(vl-princ-to-string (mapcar (function (lambda (v) (fix (+ 0.5 v)))) (ard:mat-apply (ard:mat-mul (list 1.0 0.0 0.0 1.0 1.0 2.0) (list 0.0 1.0 -1.0 0.0 0.0 0.0)) (list 1.0 0.0))))',
     "(1 3)"),
    ("arc_quarter_extremes", '(progn (setq p (ard:arc-pts 0.0 0.0 10.0 0.0 (/ pi 2.0) (list 1.0 0.0 0.0 1.0 0.0 0.0))) (strcat (rtos (apply (quote max) (mapcar (quote car) p)) 2 4) "," (rtos (apply (quote min) (mapcar (quote car) p)) 2 4) "," (rtos (apply (quote max) (mapcar (quote cadr) p)) 2 4)))',
     "10,0,10"),
    ("arc_circle_extremes", '(progn (setq p (ard:arc-pts 5.0 5.0 2.0 0.0 (* 2.0 pi) (list 1.0 0.0 0.0 1.0 0.0 0.0))) (strcat (rtos (apply (quote min) (mapcar (quote cadr) p)) 2 4) "," (rtos (apply (quote max) (mapcar (quote cadr) p)) 2 4)))',
     "3,7"),
    ("arc_transformed_by_matrix", '(progn (setq p (ard:arc-pts 0.0 0.0 10.0 0.0 (/ pi 2.0) (list 2.0 0.0 0.0 2.0 100.0 0.0))) (strcat (rtos (apply (quote max) (mapcar (quote car) p)) 2 4) "," (rtos (apply (quote max) (mapcar (quote cadr) p)) 2 4)))',
     "120,20"),
    ("bulge_semicircle_dips_right", '(progn (setq p (ard:bulge-pts (list 0.0 0.0) (list 10.0 0.0) 1.0 (list 1.0 0.0 0.0 1.0 0.0 0.0))) (rtos (apply (quote min) (mapcar (quote cadr) p)) 2 4))', "-5"),
    ("bulge_negative_bulges_left", '(progn (setq p (ard:bulge-pts (list 0.0 0.0) (list 10.0 0.0) -1.0 (list 1.0 0.0 0.0 1.0 0.0 0.0))) (rtos (apply (quote max) (mapcar (quote cadr) p)) 2 4))', "5"),
    ("bulge_zero_is_chord", '(vl-princ-to-string (length (ard:bulge-pts (list 0.0 0.0) (list 10.0 0.0) 0.0 (list 1.0 0.0 0.0 1.0 0.0 0.0))))', "2"),
    ("stamp_pad", '(ard:stamp-of "20260930.12")', "20260930_120000"),
    ("stamp_nofrac", '(ard:stamp-of "20260930")', "20260930_000000"),
    ("stamp_full", '(ard:stamp-of "20260930.123456")', "20260930_123456"),
    ("kind_elbow_v2", '(ard:kind-from-name "SCADA_V2$SCADA_TRAY_ELBOW_V2")', "ELBOW"),
    ("kind_tee_basic_lower", '(ard:kind-from-name "scada_basic$scada_tray_tee")', "TEE"),
    ("kind_cross_xref", '(ard:kind-from-name (strcat "xref" (chr 124) "SCADA_TRAY_CROSS_V2"))', "CROSS"),
    ("kind_other_future_profile", '(ard:kind-from-name "SCADA_V9$SCADA_TRAY_ELBOW_V9")', "ELBOW"),
    ("kind_unrelated", '(vl-princ-to-string (ard:kind-from-name "DOOR"))', "nil"),
    ("prefix_v2", '(ard:profile-prefix "SCADA_V2$SCADA_TRAY_ELBOW_V2")', "SCADA_V2"),
    ("prefix_none", '(vl-princ-to-string (ard:profile-prefix "SCADA_TRAY_TEE"))', "nil"),
    ("prefix_xref", '(ard:profile-prefix (strcat "x" (chr 124) "SCADA_BASIC$SCADA_TRAY_TEE"))', "SCADA_BASIC"),
    ("profile_of_default", '(ard:profile-of "SCADA_TRAY_TEE")', "DEFAULT"),
    ("face_min_picks_nearest_in_corridor",
     '(progn (setq f (ard:face (list (list 5.0 1.0 "h1") (list 5.0 -1.0 "h1") (list 20.0 0.0 "h2") (list 3.0 50.0 "h3") (list -4.0 0.0 "h4")) (list 0.0 0.0) (list 1.0 0.0) (list 0.0 1.0) 10.0 (quote MIN))) (strcat (rtos (car f) 2 4) "," (rtos (cadr f) 2 4) "," (rtos (caddr f) 2 4) "," (itoa (nth 3 f)) "," (vl-prin1-to-string (nth 4 f))))',
     '5,-1,1,2,("h1")'),
    ("face_max_unrestricted",
     '(progn (setq f (ard:face (list (list 5.0 1.0) (list 30.0 400.0) (list 30.0 -200.0) (list 2.0 0.0)) (list 0.0 0.0) (list 1.0 0.0) (list 0.0 1.0) 1.0e12 (quote MAX))) (strcat (rtos (car f) 2 4) "," (rtos (cadr f) 2 4) "," (rtos (caddr f) 2 4)))',
     "30,-200,400"),
    ("face_empty", '(vl-princ-to-string (ard:face nil (list 0.0 0.0) (list 1.0 0.0) (list 0.0 1.0) 5.0 (quote MIN)))', "nil"),
    ("dedupe_arms_same_angle", '(itoa (length (ard:dedupe-arms (list (list "W" pi nil "a" "p" 1.0) (list "W" (- pi) nil "b" "p" 1.0) (list "N" (/ pi 2.0) nil "c" "p" 1.0)))))', "2"),
    ("unique_nums", '(vl-princ-to-string (ard:unique-nums (list 300.0 300.0000001 450.0)))', "(300.0 450.0)"),
    ("hex2", '(ard:hex2 27)', "1b"),
    ("str_replace_multi", '(ard:str-replace "a--b--c" "--" "+")', "a+b+c"),
    ("take", '(vl-princ-to-string (ard:take (list 1 2 3 4) 2))', "(1 2)"),
    ("tp_true_false", '(strcat (if (ard:tp (ard:bool T)) "1" "0") (if (ard:tp (ard:bool nil)) "1" "0"))', "10"),
    ("opening_from_caps_and_rails", '(progn (setq sg (list (list (list 0.0 0.0) (list 0.0 10.0)) (list (list 0.0 100.0) (list 0.0 110.0)) (list (list 0.0 0.0) (list 100.0 0.0)) (list (list 0.0 10.0) (list 100.0 10.0)) (list (list 0.0 100.0) (list 100.0 100.0)) (list (list 0.0 110.0) (list 100.0 110.0)))) (setq pp (apply (quote append) sg)) (setq o (ard:derive-openings sg pp)) (strcat (itoa (length o)) "|" (rtos (car (cdr (assoc "center" (car o)))) 2 3) "," (rtos (cadr (cdr (assoc "center" (car o)))) 2 3) "," (rtos (car (cdr (assoc "normal" (car o)))) 2 3) "," (rtos (cdr (assoc "width_outer" (car o))) 2 3) "," (rtos (cdr (assoc "width_inner" (car o))) 2 3) "," (rtos (cdr (assoc "width_center_to_center" (car o))) 2 3)))', "1|0,55,-1,110,90,100"),
    ("caps_without_rail_edges_are_not_an_opening", '(progn (setq sg (list (list (list 0.0 0.0) (list 0.0 10.0)) (list (list 0.0 100.0) (list 0.0 110.0)))) (setq pp (apply (quote append) sg)) (itoa (length (ard:derive-openings sg pp))))', "0"),
    ("geometry_beyond_the_caps_blocks_the_opening", '(progn (setq sg (list (list (list 0.0 0.0) (list 0.0 10.0)) (list (list 0.0 100.0) (list 0.0 110.0)) (list (list 0.0 0.0) (list 100.0 0.0)) (list (list 0.0 10.0) (list 100.0 10.0)) (list (list 0.0 100.0) (list 100.0 100.0)) (list (list 0.0 110.0) (list 100.0 110.0)))) (setq sg (cons (list (list -50.0 50.0) (list -60.0 50.0)) sg)) (setq pp (apply (quote append) sg)) (itoa (length (ard:derive-openings sg pp))))', "0"),
    ("protrusion_outside_the_rail_strip_does_not_block", '(progn (setq sg (list (list (list 0.0 0.0) (list 0.0 10.0)) (list (list 0.0 100.0) (list 0.0 110.0)) (list (list 0.0 0.0) (list 100.0 0.0)) (list (list 0.0 10.0) (list 100.0 10.0)) (list (list 0.0 100.0) (list 100.0 100.0)) (list (list 0.0 110.0) (list 100.0 110.0)))) (setq sg (cons (list (list -50.0 500.0) (list -60.0 500.0)) sg)) (setq pp (apply (quote append) sg)) (itoa (length (ard:derive-openings sg pp))))', "1"),
    ("single_long_end_edge_is_not_an_opening", '(progn (setq sg (list (list (list 0.0 0.0) (list 0.0 110.0)) (list (list 0.0 0.0) (list 100.0 0.0)) (list (list 0.0 110.0) (list 100.0 110.0)))) (setq pp (apply (quote append) sg)) (itoa (length (ard:derive-openings sg pp))))', "0"),
    ("axis_joint_of_two_perpendicular_openings", '(progn (setq o (list (list (cons "normal" (list -1.0 0.0)) (cons "center" (list -10.0 5.0))) (list (cons "normal" (list 0.0 1.0)) (cons "center" (list 7.0 20.0))))) (setq j (ard:axis-joint o)) (strcat (rtos (car (car j)) 2 3) "," (rtos (cadr (car j)) 2 3) "," (rtos (cadr j) 2 3)))', "7,5,0"),
    ("axis_joint_needs_two_openings", '(vl-prin1-to-string (ard:axis-joint (list (list (cons "normal" (list 1.0 0.0)) (cons "center" (list 0.0 0.0))))))', "nil"),
    ("connection_arm_without_opening",
     '(progn (setq c (ard:connection (ard:obj (list (cons "_pts" (list (list 60.0 0.0))))) (list (cons "pt" (list 0.0 0.0 0.0))) (list "E" 0.0 (list 100.0 0.0) "H" "P" 300.0) (list (list 50.0 10.0 "S") (list 50.0 -10.0 "S")) nil T)) (ard:get "status" c))',
     "NO_OPENING"),
    ("z_normal_yes", '(vl-prin1-to-string (ard:z-normal-p (list 0.0 0.0 1.0)))', "T"),
    ("z_normal_no", '(vl-prin1-to-string (ard:z-normal-p (list 0.0 0.0 -1.0)))', "nil"),
    ("block_missing", '(vl-prin1-to-string (car (ard:block-local "NO_SUCH_BLOCK_ANYWHERE")))', "nil"),
    ("connection_without_fitting_geometry",
     '(progn (setq c (ard:connection (ard:obj (list (cons "_pts" nil))) (list (cons "pt" (list 0.0 0.0 0.0))) (list "E" 0.0 (list 100.0 0.0) "H" "P" 300.0) (list (list 50.0 10.0 "S") (list 50.0 -10.0 "S")) nil nil)) (strcat (ard:get "status" c) "|" (ard:get "reason" c)))',
     "NOT_COMPUTABLE|fitting block definition has no readable geometry"),
    ("connection_without_straight",
     '(progn (setq c (ard:connection (ard:obj (list (cons "_pts" (list (list 60.0 0.0))))) (list (cons "pt" (list 0.0 0.0 0.0))) (list "E" 0.0 (list 100.0 0.0) "H" "P" 300.0) nil nil nil)) (ard:get "status" c))',
     "NOT_COMPUTABLE"),
    ("json_writer_structure",
     '(progn (setq f (open (strcat (getvar "DWGPREFIX") "w.json") "w" "utf8")) (ard:jw (ard:obj (list (cons "a" 1) (cons "_hidden" 2) (cons "b" (ard:arr (list 1.5 T (quote ARD_FALSE) nil "x"))) (cons "c" (ard:obj nil)) (cons "d" (ard:arr nil)))) f 9) (close f) (setq f (open (strcat (getvar "DWGPREFIX") "w.json") "r")) (setq l (read-line f)) (close f) l)',
     '{"a":1,"b":[1.5,true,false,null,"x"],"c":{},"d":[]}'),
]
CASES = [c for c in CASES if c[1] is not None]

_out: dict = {}


def _run() -> str:
    if _out:
        return _out["log"]
    work = Path(tempfile.mkdtemp(prefix="ctrdiag_l1b_"))
    cmds = ['(princ (strcat (chr 10) "T:%s=" %s (chr 1)))' % (label, lisp_str(expr)) for label, expr, _ in CASES]
    log, _info = accore_run.run([REPO / "autocad_router_diagnostics.lsp"], cmds, work)
    _out["log"] = log
    _out["dir"] = work
    return log


def value_of(log: str, label: str) -> str | None:
    m = re.search(r"^T:%s=(.*?)\x01" % re.escape(label), log, flags=re.M | re.S)
    return m.group(1).replace("\r\n", "\n") if m else None


@unittest.skipUnless(Path(accore_run.ACCORE).exists(), "L1b needs AutoCAD accoreconsole.exe")
class PureLogicInEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = REPO / "output"
        cls.files_before = sorted(p.name for p in out.glob("*")) if out.exists() else []
        cls.log = _run()
        cls.files_after = sorted(p.name for p in out.glob("*")) if out.exists() else []

    def test_all_cases(self):
        failures = []
        for label, _expr, expected in CASES:
            got = value_of(self.log, label)
            if got != expected:
                failures.append("%s: expected %r got %r" % (label, expected, got))
        self.assertEqual(failures, [], "\n".join(failures))

    def test_tool_loaded_without_running_anything(self):
        # loading must not scan or write: no CTRDIAG summary line before the first test print
        head = self.log.split("T:jstr_specials=")[0]
        self.assertIsNone(re.search(r"^CTRDIAG \((all|single|export)\)", head, flags=re.M))
        self.assertIsNone(re.search(r"^(JSON|CSV|TXT) ?: ", head, flags=re.M))
        self.assertEqual(self.files_before, self.files_after, "loading the tool wrote files")
        self.assertIn("Router Diagnostics", head)


if __name__ == "__main__":
    unittest.main()
