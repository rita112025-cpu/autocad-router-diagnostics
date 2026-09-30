"""L1 (pure Python): analyze_diagnostics.py on hand-made reports.  No AutoCAD needed."""
import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import analyze_diagnostics as ad  # noqa: E402


def conn(direction, err, status=None):
    return {"direction": direction, "error_mm": err,
            "status": status or ("EXACT" if err < 0.01 else "MISMATCH")}


def fitting(handle, ftype="ELBOW", prefix="SCADA_V2", rot=90.0, err=0.0, status="OK", issues=(),
            dirs=("W", "S"), profiles=("SCADA_V2",), block_coords=(576.0, -576.0), trans=None, paths=("P1",)):
    return {
        "handle": handle, "raw_block_name": "%s$SCADA_TRAY_%s_V2" % (prefix, ftype) if prefix else "SCADA_TRAY_" + ftype,
        "resolved_profile_prefix": prefix, "profile": prefix or "DEFAULT", "fitting_type": ftype,
        "insert_x": 1.0, "insert_y": 2.0, "insert_z": 0.0, "scale_x": 0.5, "scale_y": 0.5, "scale_z": 0.5,
        "rotation_deg": rot, "status": status, "max_connection_error_mm": err,
        "junction": {"junction_x": 10.0, "junction_y": 20.0, "directions": list(dirs), "classification": ftype,
                    "profiles": list(profiles)},
        "junction_in_block_coords": list(block_coords),
        "translation_fit": trans,
        "connected_path_candidates": [{"handle": p, "relation": "exact", "touches_junction": True} for p in paths]
                                     + [{"handle": "FAR", "relation": "unrelated", "touches_junction": False}],
        "issues": [{"severity": s, "code": c, "detail": d} for s, c, d in issues],
    }


def report(fittings, paths=None, junctions=None, warnings=None, mode="all"):
    return {"schema_version": "1.0", "mode": mode, "drawing": "T.dwg", "timestamp": "20260101_000000",
            "fittings": fittings, "paths": paths if paths is not None else [], "junctions": junctions or [],
            "warnings": warnings or []}


class CountsAndRanking(unittest.TestCase):
    def setUp(self):
        self.rep = report(
            [fitting("A", "ELBOW", "SCADA_V2", err=12.5, status="FAIL",
                     issues=[("FAIL", "CONNECTION_MISMATCH", "arm W")]),
             fitting("B", "TEE", "SCADA_BASIC", err=0.2, status="WARN",
                     issues=[("WARN", "CONNECTION_NEAR", "arm E")]),
             fitting("C", "CROSS", "SCADA_V2", err=0.0),
             fitting("D", "ELBOW", None, err=None, status="NOT_COMPUTABLE")],
            paths=[{"handle": "P1", "profile": "SCADA_V2", "profile_explicit": True},
                   {"handle": "P2", "profile": "DEFAULT", "profile_explicit": False},
                   {"handle": "P3", "profile": "SCADA_BASIC", "profile_explicit": True}])
        self.res = ad.analyze(self.rep)

    def test_counts(self):
        self.assertEqual(self.res["fitting_count"], 4)
        self.assertEqual(self.res["fitting_types"], {"CROSS": 1, "ELBOW": 2, "TEE": 1})
        self.assertEqual(self.res["path_count"], 3)

    def test_basic_v2_families(self):
        self.assertEqual(self.res["fitting_profile_families"], {"BASIC": 1, "DEFAULT": 1, "V2": 2})
        self.assertEqual(self.res["fitting_profile_prefixes"], {"(none)": 1, "SCADA_BASIC": 1, "SCADA_V2": 2})
        self.assertEqual(self.res["path_profile_families"], {"BASIC": 1, "DEFAULT": 1, "V2": 1})

    def test_largest_error(self):
        self.assertEqual(self.res["largest_connection_error"]["handle"], "A")
        self.assertEqual(self.res["largest_connection_error"]["error_mm"], 12.5)
        self.assertEqual([w["handle"] for w in self.res["worst_fittings"]], ["A", "B", "C"])

    def test_problems_sorted_fail_before_warn(self):
        sev = [p["severity"] for p in self.res["problems"]]
        self.assertEqual(sev, sorted(sev, key=lambda s: {"FAIL": 0, "WARN": 1}.get(s, 2)))
        codes = {(p["object"], p["handle"], p["code"]) for p in self.res["problems"]}
        self.assertIn(("FITTING", "A", "CONNECTION_MISMATCH"), codes)
        self.assertIn(("FITTING", "B", "CONNECTION_NEAR"), codes)
        self.assertIn(("FITTING", "D", "NOT_COMPUTABLE"), codes)
        self.assertIn(("PATH", "P2", "PATH_PROFILE_IMPLICIT"), codes)

    def test_per_fitting_rows(self):
        row = self.res["fittings"][0]
        for key in ("handle", "block", "position", "rotation_deg", "scale", "connected_paths",
                    "max_connection_error_mm", "status"):
            self.assertIn(key, row)
        self.assertEqual(row["connected_paths"], ["P1"])          # 'FAR' is unrelated
        self.assertEqual(row["position"], [1.0, 2.0, 0.0])
        self.assertEqual(row["scale"], [0.5, 0.5, 0.5])

    def test_status_counts(self):
        self.assertEqual(self.res["status_counts"], {"FAIL": 1, "WARN": 1, "OK": 1, "NOT_COMPUTABLE": 1})


class ProfileMismatch(unittest.TestCase):
    def test_fitting_and_path_profile_mismatch(self):
        f = fitting("E1", profiles=("SCADA_BASIC", "SCADA_V2"), status="FAIL",
                    issues=[("FAIL", "FITTING_PROFILE_MISMATCH", "fitting SCADA_V2 vs PATH SCADA_BASIC"),
                            ("FAIL", "PATH_PROFILE_MISMATCH", "mixed")])
        j = {"junction_x": 10.0, "junction_y": 20.0, "fitting_handles": ["E1"],
             "arms": [{"path_handle": "P1", "direction": "W", "profile": "SCADA_V2"},
                      {"path_handle": "P2", "direction": "S", "profile": "SCADA_BASIC"}],
             "issues": [{"severity": "FAIL", "code": "PATH_PROFILE_MISMATCH", "detail": "x"}]}
        res = ad.analyze(report([f], junctions=[j]))
        self.assertEqual(len(res["profile_mismatch"]), 1)
        self.assertEqual(res["profile_mismatch"][0]["fitting"], "E1")
        self.assertEqual(len(res["path_profile_conflicts"]), 1)
        self.assertEqual([a["profile"] for a in res["path_profile_conflicts"][0]["arms"]],
                         ["SCADA_V2", "SCADA_BASIC"])
        self.assertIn("PROFILE_MISMATCH: 2", ad.format_text(res))

    def test_no_mismatch(self):
        res = ad.analyze(report([fitting("OK1")]))
        self.assertEqual(res["profile_mismatch"], [])


class Consistency(unittest.TestCase):
    def make(self, block_coords_by_rot, trans_by_rot):
        fs = []
        for i, ((rot, dirs), bc) in enumerate(block_coords_by_rot):
            fs.append(fitting("F%d" % i, rot=rot, dirs=dirs, block_coords=bc, err=100.0, status="FAIL",
                              trans={"in_block_coords": trans_by_rot[i], "magnitude_mm": 400.0}))
        return ad.analyze(report(fs))["consistency"]

    def test_systematic_block_origin_error_is_recognised(self):
        c = self.make([((180.0, ("E", "S")), (576.0, -576.0)), ((90.0, ("W", "S")), (576.0, -576.0)),
                       ((180.0, ("E", "S")), (576.0, -576.0))],
                      [(-686.7, 521.0)] * 3)
        by = {x["check"]: x for x in c}
        self.assertTrue(by["JUNCTION_IN_BLOCK_COORDS_CONSTANT"]["consistent"])
        self.assertTrue(by["TRANSLATION_IN_BLOCK_COORDS_CONSTANT"]["consistent"])
        self.assertTrue(by["ROTATION_FUNCTION_OF_DIRECTIONS"]["consistent"])

    def test_rotation_dependent_error_is_flagged(self):
        c = self.make([((180.0, ("E", "S")), (576.0, -576.0)), ((90.0, ("W", "S")), (500.0, -576.0))],
                      [(-686.7, 521.0), (10.0, 20.0)])
        by = {x["check"]: x for x in c}
        self.assertFalse(by["JUNCTION_IN_BLOCK_COORDS_CONSTANT"]["consistent"])
        self.assertFalse(by["TRANSLATION_IN_BLOCK_COORDS_CONSTANT"]["consistent"])

    def test_same_directions_different_rotation_is_flagged(self):
        c = self.make([((180.0, ("E", "S")), (576.0, -576.0)), ((90.0, ("E", "S")), (576.0, -576.0))],
                      [(0.0, 0.0), (0.0, 0.0)])
        by = {x["check"]: x for x in c}
        self.assertFalse(by["ROTATION_FUNCTION_OF_DIRECTIONS"]["consistent"])


class RobustInput(unittest.TestCase):
    def test_empty(self):
        res = ad.analyze(report([]))
        self.assertIsNone(res["largest_connection_error"])
        self.assertEqual(res["fitting_count"], 0)
        self.assertIn("none computable", ad.format_text(res))

    def test_export_mode_without_analysis_fields(self):
        raw = {"handle": "X", "raw_block_name": "SCADA_V2$SCADA_TRAY_TEE_V2", "resolved_profile_prefix": "SCADA_V2",
               "profile": "SCADA_V2", "fitting_type": "TEE", "insert_x": 1, "insert_y": 2, "insert_z": 0,
               "scale_x": 1, "scale_y": 1, "scale_z": 1, "rotation_deg": 0}
        res = ad.analyze(report([raw], mode="export"))
        self.assertEqual(res["fitting_types"], {"TEE": 1})
        self.assertEqual(res["fittings"][0]["status"], None)
        ad.format_text(res)

    def test_not_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.json"
            p.write_text('{"a": 1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                ad.load(p)

    def test_bad_arrays(self):
        with self.assertRaises(ValueError):
            ad.analyze({"fittings": {}, "paths": []})

    def test_utf8_bom_and_non_ascii(self):
        rep = report([fitting("A")], paths=[{"handle": "P", "profile": 'we"ird,prof\\x 中文',
                                            "profile_explicit": True}])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bom.json"
            p.write_bytes(b"\xef\xbb\xbf" + json.dumps(rep, ensure_ascii=False).encode("utf-8"))
            res = ad.analyze(ad.load(p))
        self.assertEqual(res["path_count"], 1)


class CommandLine(unittest.TestCase):
    def run_cli(self, rep, *args):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(rep), encoding="utf-8")
            return subprocess.run([sys.executable, str(REPO / "analyze_diagnostics.py"), str(p), *args],
                                  capture_output=True, text=True, encoding="utf-8")

    def test_text_output_lists_required_sections(self):
        r = self.run_cli(report([fitting("A", err=5.0, status="FAIL", issues=[("FAIL", "CONNECTION_MISMATCH", "d")])]))
        self.assertEqual(r.returncode, 0, r.stderr)
        for token in ("1. fittings: 1", "2. by type", "3. by profile", "4. PATHs", "5. PROFILE_MISMATCH",
                      "6. largest connection error", "7. FAIL / WARN", "8. fittings:"):
            self.assertIn(token, r.stdout)

    def test_json_output_is_valid_json(self):
        r = self.run_cli(report([fitting("A")]), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["fitting_count"], 1)

    def test_strict_exit_code(self):
        bad = report([fitting("A", status="FAIL", issues=[("FAIL", "CONNECTION_MISMATCH", "d")])])
        self.assertEqual(self.run_cli(bad, "--strict").returncode, 1)
        self.assertEqual(self.run_cli(report([fitting("A")]), "--strict").returncode, 0)

    def test_missing_file(self):
        r = subprocess.run([sys.executable, str(REPO / "analyze_diagnostics.py"), "nope.json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class CsvJsonEscapingConsumption(unittest.TestCase):
    """The consumer side of the escaping contract (the producer side is tested in L1b / L2)."""

    NASTY = 'a"b,c\\d\ne\tf 中文'

    def test_json_roundtrip(self):
        self.assertEqual(json.loads(json.dumps({"v": self.NASTY}))["v"], self.NASTY)

    def test_csv_roundtrip(self):
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerow(["x", self.NASTY, "y"])
        row = next(csv.reader(io.StringIO(buf.getvalue())))
        self.assertEqual(row, ["x", self.NASTY, "y"])


if __name__ == "__main__":
    unittest.main()
