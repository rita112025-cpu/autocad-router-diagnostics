"""L2: known-answer scenes built in a DISPOSABLE drawing inside the real AutoCAD engine (accoreconsole),
then the read-only tool runs on them and its JSON/CSV/TXT is checked against answers derived
independently in tests/harness/scenes.lsp (not by the tool).

Every scene also dumps the whole drawing database (entities, XDATA, tables, HANDSEED) before and after
the tool ran; they must be byte-identical (read-only proof).
"""
import csv
import json
import math
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine_runner as er  # noqa: E402
import analyze_diagnostics as ad  # noqa: E402

ROOT: Path | None = None
T = 1e-6


def setUpModule():
    global ROOT
    if not er.engine_available():
        raise unittest.SkipTest("L2 needs AutoCAD accoreconsole.exe (see README: test levels)")
    ROOT = er.run_all()


def rep(scene, mode="all"):
    return er.latest_json(ROOT, scene, mode)


def fit(scene, mode="all", index=0):
    return rep(scene, mode)["fittings"][index]


def arm(f, direction):
    return next(c for c in f["connections"] if c["direction"] == direction)


def read_csv(path, dict_rows=True):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle)) if dict_rows else list(csv.reader(handle))


def codes(obj):
    return [i["code"] for i in obj["issues"]]


class Engine(unittest.TestCase):
    def test_no_engine_or_script_errors(self):
        self.assertEqual(er.errors(ROOT), [])
        log = er.console(ROOT)
        self.assertIsNone(re.search(r"^\w+ stopped \(diagnosis only", log, flags=re.M))
        self.assertIsNone(re.search(r"^; (error|錯誤)", log, flags=re.M), "engine reported a LISP error")

    def test_every_scene_produced_the_three_files(self):
        for scene in er.SCENES:
            for mode_dir in (ROOT / scene).iterdir():
                if not mode_dir.is_dir():
                    continue
                names = sorted(p.name for p in mode_dir.iterdir())
                suffix = {"all": "_all", "export": "_export", "single": ""}[mode_dir.name]
                pat = re.compile(r"^ctrdiag_\d{8}_\d{6}%s\.(json|csv|txt)$" % suffix)
                self.assertEqual(len(names), 3, (scene, names))
                for n in names:
                    self.assertRegex(n, pat)


class ReadOnlyProof(unittest.TestCase):
    def test_database_identical_before_and_after_every_scene(self):
        checked = 0
        for scene in er.SCENES:
            before = (ROOT / (scene + "_before.txt")).read_bytes()
            after = (ROOT / (scene + "_after.txt")).read_bytes()
            self.assertGreater(len(before), 200, scene)
            self.assertEqual(before, after, "drawing database changed while running the tool on " + scene)
            checked += 1
        self.assertEqual(checked, len(er.SCENES))

    def test_scene_that_runs_all_three_commands(self):
        for mode in ("all", "export", "single"):
            self.assertEqual(rep("readonly", mode)["read_only"], True)
        self.assertEqual(rep("readonly", "all")["mode"], "all")
        self.assertEqual(rep("readonly", "export")["mode"], "export")
        self.assertEqual(rep("readonly", "single")["mode"], "single")


class PathReading(unittest.TestCase):
    def test_line_vertices(self):
        for mode in ("export", "all"):
            paths = rep("line-path", mode)["paths"]
            self.assertEqual(len(paths), 1)
            p = paths[0]
            self.assertEqual(p["entity_type"], "LINE")
            self.assertEqual([(v["index"], v["x"], v["y"], v["z"]) for v in p["vertices"]],
                             [(0, 10, 20, 5), (1, 110, 20, 5)])
            self.assertEqual((p["profile"], p["width"]), ("SCADA_V2", 450))
            self.assertTrue(p["profile_explicit"] and p["width_explicit"] and p["has_ctr_path_xdata"])
            self.assertEqual(p["layer"], "SCADA-TRAY-PATH")

    def test_xdata_raw_values(self):
        raw = rep("line-path")["paths"][0]["xdata_raw"]
        self.assertEqual([(r["app"], r["code"], r["value"]) for r in raw],
                         [("CTR_PATH", 1000, "PATH"), ("CTR_PATH", 1040, 450),
                          ("CTR_PATH", 1000, "PROFILE=SCADA_V2")])

    def test_lwpolyline_all_vertices_not_just_ends(self):
        paths = rep("lw-multi", "export")["paths"]
        multi = next(p for p in paths if p["vertex_count"] == 6)
        self.assertEqual(multi["entity_type"], "LWPOLYLINE")
        self.assertFalse(multi["closed"])
        self.assertEqual([(v["x"], v["y"]) for v in multi["vertices"]],
                         [(0, 0), (100, 0), (100, 100), (200, 100), (200, -50), (0, -50)])
        self.assertEqual([v["index"] for v in multi["vertices"]], list(range(6)))
        self.assertTrue(all(v["bulge"] == 0 for v in multi["vertices"]))

    def test_closed_lwpolyline_with_bulge(self):
        paths = rep("lw-multi", "export")["paths"]
        poly = next(p for p in paths if p["vertex_count"] == 4)
        self.assertTrue(poly["closed"])
        self.assertTrue(poly["has_bulge"])
        self.assertEqual(poly["vertices"][0]["bulge"], 0.5)
        self.assertEqual(poly["profile"], "DEFAULT")            # no XDATA on this one
        self.assertFalse(poly["profile_explicit"])
        warn = [w["code"] for w in rep("lw-multi")["warnings"]]
        self.assertEqual(warn.count("ARC_SEGMENT_TREATED_AS_CHORD"), 1)

    def test_topology_of_multi_vertex_path(self):
        r = rep("lw-multi")
        bends = [j for j in r["junctions"] if j["layout"] == "Model"]
        self.assertEqual(len(bends), 8)                      # 4 bends open polyline + 4 corners of the square
        self.assertTrue(all(j["classification"] == "ELBOW" for j in bends))
        self.assertTrue(all("NO_FITTING_AT_JUNCTION" in codes(j) for j in bends))

    def test_no_xdata_means_router_defaults_and_is_reported(self):
        r = rep("no-xdata")
        for p in r["paths"]:
            self.assertEqual((p["profile"], p["width"]), ("DEFAULT", 300))
            self.assertFalse(p["profile_explicit"])
            self.assertFalse(p["width_explicit"])
            self.assertFalse(p["has_ctr_path_xdata"])
            self.assertEqual(p["xdata_raw"], [])
        f = r["fittings"][0]
        self.assertEqual((f["raw_block_name"], f["profile"], f["resolved_profile_prefix"]),
                         ("SCADA_TRAY_ELBOW", "DEFAULT", None))
        self.assertEqual(f["status"], "OK")
        rows = read_csv(next((ROOT / "no-xdata" / "all").glob("*.csv")))
        path_rows = [x for x in rows if x["object_type"] == "PATH"]
        self.assertEqual([x["status"] for x in path_rows], ["WARN", "WARN"])
        self.assertTrue(all("PROFILE_IMPLICIT_DEFAULT" in x["issues"] for x in path_rows))
        problems = ad.analyze(r)["problems"]
        self.assertEqual(sum(1 for p in problems if p["code"] == "PATH_PROFILE_IMPLICIT"), 2)


class FittingRecords(unittest.TestCase):
    CASES = [("elbow-r0", 0.0, 1.0, ["E", "N"], (1000.0, 2000.0)),
             ("elbow-r1", 90.0, 0.5, ["W", "N"], (1000.0, 2000.0)),
             ("elbow-r2", 180.0, 2.0, ["W", "S"], (1000.0, 2000.0)),
             ("elbow-r3", 270.0, 0.4815924915, ["E", "S"], (8766.7604, 4929.3801))]

    def test_rotation_scale_and_direction_for_0_90_180_270(self):
        for scene, rot, scale, dirs, j in self.CASES:
            with self.subTest(scene=scene):
                f = fit(scene)
                self.assertAlmostEqual(f["rotation_deg"], rot, places=6)
                self.assertAlmostEqual(f["rotation_rad"], math.radians(rot), places=8)
                self.assertEqual([f["scale_x"], f["scale_y"], f["scale_z"]], [scale] * 3)
                self.assertEqual(f["entity_type"], "INSERT")
                self.assertEqual(f["layer"], "SCADA-TRAY")
                self.assertEqual(f["junction"]["directions"], dirs)
                self.assertEqual(f["junction"]["classification"], "ELBOW")
                self.assertAlmostEqual(f["junction"]["junction_x"], j[0], places=6)
                self.assertAlmostEqual(f["junction"]["junction_y"], j[1], places=6)
                self.assertEqual(f["status"], "OK", f["issues"])
                self.assertLess(f["max_connection_error_mm"], T)
                self.assertEqual([c["status"] for c in f["connections"]], ["EXACT", "EXACT"])
                self.assertEqual(sorted(c["direction"] for c in f["connections"]), sorted(dirs))
                # the junction must sit at the block's own joint point, whatever the rotation/scale
                for got, want in zip(f["junction_in_block_coords"], (100.0, -50.0)):
                    self.assertAlmostEqual(got, want, places=6)
                self.assertLess(f["translation_fit"]["magnitude_mm"], T)

    def test_required_fitting_fields_present(self):
        f = fit("elbow-r1")
        for key in ("entity_type", "handle", "raw_block_name", "effective_name", "resolved_profile_prefix",
                    "fitting_type", "insert_x", "insert_y", "insert_z", "scale_x", "scale_y", "scale_z",
                    "rotation_deg", "rotation_rad", "layer", "bounding_box_min", "bounding_box_max",
                    "xdata_raw", "profile", "junction", "connections", "connected_path_candidates", "status"):
            self.assertIn(key, f)
        self.assertEqual(f["raw_block_name"], "SCADA_V2$SCADA_TRAY_ELBOW_V2")
        self.assertEqual(f["resolved_profile_prefix"], "SCADA_V2")
        self.assertEqual(f["fitting_type_source"], "block_name")
        self.assertEqual(f["xdata_raw"][0]["app"], "CTR_GEN")
        self.assertEqual(f["xdata_raw"][0]["value"], "ELBOW")

    def test_bounding_box_is_computed_from_block_definition(self):
        f = fit("elbow-r0")                       # s=1, rot 0, joint (100,-50) at (1000,2000): ip=(900,2050)
        self.assertEqual(f["bounding_box_source"], "computed_from_block_definition")
        self.assertEqual(f["bounding_box_min"][:2], [840.0, 1840.0])
        self.assertEqual(f["bounding_box_max"][:2], [1300.0, 2300.0])

    def test_basic_and_v2_blocks(self):
        b = fit("basic-elbow")
        self.assertEqual((b["resolved_profile_prefix"], b["profile"], b["status"]), ("SCADA_BASIC", "SCADA_BASIC", "OK"))
        self.assertEqual(b["junction"]["directions"], ["W", "N"])
        v = fit("elbow-r0")
        self.assertEqual((v["resolved_profile_prefix"], v["profile"]), ("SCADA_V2", "SCADA_V2"))

    def test_elbow_tee_cross_topology(self):
        e = fit("elbow-r0")
        self.assertEqual((e["junction"]["classification"], e["junction"]["degree"]), ("ELBOW", 2))
        t0 = fit("tee-r0")
        self.assertEqual((t0["junction"]["classification"], t0["junction"]["degree"], t0["junction"]["directions"]),
                         ("TEE", 3, ["E", "W", "N"]))
        self.assertEqual(len(t0["connections"]), 3)
        self.assertLess(t0["max_connection_error_mm"], T)
        t3 = fit("tee-r3")
        self.assertEqual(t3["junction"]["directions"], ["E", "N", "S"])
        self.assertEqual(t3["status"], "OK", t3["issues"])
        self.assertAlmostEqual(t3["rotation_deg"], 270.0, places=6)
        x = fit("cross")
        self.assertEqual((x["junction"]["classification"], x["junction"]["degree"], x["junction"]["directions"]),
                         ("CROSS", 4, ["E", "W", "N", "S"]))
        self.assertEqual(x["status"], "OK", x["issues"])
        self.assertEqual([c["status"] for c in x["connections"]], ["EXACT"] * 4)
        self.assertAlmostEqual(x["junction"]["junction_x"], 300.0, places=6)
        self.assertAlmostEqual(x["junction"]["junction_y"], 400.0, places=6)

    def test_connection_fields_per_arm(self):
        c = arm(fit("elbow-r0"), "E")
        for key in ("direction", "expected", "actual", "delta_x", "delta_y", "error_mm", "status",
                    "axial_error_mm", "lateral_error_mm", "straight_end_width_mm", "fitting_opening_width_mm",
                    "expected_in_block_coords", "actual_in_block_coords", "delta_in_block_coords", "straight_handles"):
            self.assertIn(key, c)
        # E arm of an unrotated elbow with joint (1000,2000) and takeoff 300: Straight starts at x=1300
        self.assertEqual(c["expected"], [1300.0, 2000.0, 0.0])
        self.assertEqual(c["actual"], [1300.0, 2000.0, 0.0])
        self.assertEqual((c["straight_end_width_mm"], c["fitting_opening_width_mm"]), (320.0, 320.0))
        self.assertGreaterEqual(len(c["straight_handles"]), 2)


class Mismatch(unittest.TestCase):
    def test_mixed_basic_v2_paths(self):
        f = fit("mixed-paths")
        self.assertEqual(f["status"], "FAIL")
        self.assertIn("PATH_PROFILE_MISMATCH", codes(f))
        self.assertIn("FITTING_PROFILE_MISMATCH", codes(f))
        self.assertEqual(sorted(f["junction"]["profiles"]), ["SCADA_BASIC", "SCADA_V2"])
        self.assertEqual(f["junction"]["classification"], "ELBOW")        # topology itself is fine
        self.assertTrue(all(c["status"] == "EXACT" for c in f["connections"]))
        j = rep("mixed-paths")["junctions"][0]
        self.assertIn("PATH_PROFILE_MISMATCH", codes(j))
        res = ad.analyze(rep("mixed-paths"))
        self.assertEqual(len(res["profile_mismatch"]), 1)
        self.assertEqual(len(res["path_profile_conflicts"]), 1)
        self.assertEqual(sorted(a["profile"] for a in res["path_profile_conflicts"][0]["arms"]),
                         ["SCADA_BASIC", "SCADA_V2"])

    def test_profile_mismatch_fitting_only(self):
        f = fit("profile-mismatch")
        self.assertEqual(f["status"], "FAIL")
        self.assertEqual(codes(f), ["FITTING_PROFILE_MISMATCH"])
        self.assertIn("SCADA_V2", f["issues"][0]["detail"])
        self.assertIn("SCADA_BASIC", f["issues"][0]["detail"])
        self.assertEqual([c["status"] for c in f["connections"]], ["EXACT", "EXACT"])   # geometry is fine

    def test_fitting_type_vs_topology(self):
        f = fit("topology-mismatch")
        self.assertEqual(f["fitting_type"], "TEE")
        self.assertEqual(f["junction"]["classification"], "ELBOW")
        self.assertIn("FITTING_TOPOLOGY_MISMATCH", codes(f))
        self.assertEqual(f["status"], "FAIL")

    def test_rotation_error(self):
        f = fit("rot-error")
        self.assertEqual(f["status"], "FAIL")
        self.assertEqual(f["junction"]["directions"], ["W", "S"])
        self.assertEqual(arm(f, "W")["status"], "EXACT")
        s_arm = arm(f, "S")
        self.assertEqual(s_arm["status"], "NO_OPENING")          # rotated fitting has no opening facing S
        self.assertIsNone(s_arm["error_mm"])
        self.assertIn("ARM_WITHOUT_OPENING", codes(f))
        self.assertIn("OPENING_WITHOUT_ARM", codes(f))           # ... but one facing N where the PATH has no arm
        self.assertEqual(sorted(o["facing"] for o in f["openings"]), ["N", "W"])

    def test_takeoff_error_is_axial_only(self):
        f = fit("takeoff-error")
        self.assertEqual(f["status"], "FAIL")
        for c in f["connections"]:
            self.assertEqual(c["status"], "MISMATCH")
            self.assertAlmostEqual(c["axial_error_mm"], -5.0, places=6)      # 5 mm gap
            self.assertAlmostEqual(c["lateral_error_mm"], 0.0, places=6)
            self.assertAlmostEqual(c["error_mm"], 5.0, places=6)
        t = f["translation_fit"]
        self.assertLess(t["magnitude_mm"], T)
        self.assertTrue(all(abs(p["axial_residual_mm"] + 5.0) < T for p in t["per_arm"]))
        self.assertTrue(any(h.startswith("ARM_LENGTH_OR_TAKEOFF") for h in t["hints"]))
        self.assertFalse(any(h.startswith("PLACEMENT_OFFSET") for h in t["hints"]))

    def test_placement_offset_is_a_pure_translation(self):
        f = fit("offset-error")
        self.assertEqual(f["status"], "FAIL")
        for c in f["connections"]:
            self.assertAlmostEqual(c["delta_x"], -3.0, places=6)     # delta = Straight - opening
            self.assertAlmostEqual(c["delta_y"], -4.0, places=6)
            self.assertAlmostEqual(c["error_mm"], 5.0, places=6)
        t = f["translation_fit"]
        self.assertAlmostEqual(t["dx"], 3.0, places=6)
        self.assertAlmostEqual(t["dy"], 4.0, places=6)
        self.assertAlmostEqual(t["magnitude_mm"], 5.0, places=6)
        self.assertAlmostEqual(t["in_block_coords"][0], 3.0, places=6)      # rot 0, scale 1
        self.assertAlmostEqual(t["in_block_coords"][1], 4.0, places=6)
        self.assertLess(t["rms_lateral_residual_mm"], T)
        self.assertTrue(all(abs(p["axial_residual_mm"]) < T for p in t["per_arm"]))
        self.assertTrue(any(h.startswith("PLACEMENT_OFFSET") for h in t["hints"]))


class DetectionIsPatternBased(unittest.TestCase):
    def test_unknown_future_profile_is_still_a_fitting(self):
        f = fit("future-profile")
        self.assertEqual((f["raw_block_name"], f["fitting_type"], f["fitting_type_source"]),
                         ("SCADA_V9$SCADA_TRAY_ELBOW_V9", "ELBOW", "block_name"))
        self.assertEqual((f["resolved_profile_prefix"], f["profile"], f["status"]), ("SCADA_V9", "SCADA_V9", "OK"))
        self.assertEqual(f["junction"]["directions"], ["E", "S"])

    def test_fitting_recognised_by_xdata_tag_when_name_has_no_pattern(self):
        f = fit("xdata-tag-fitting")
        self.assertEqual((f["raw_block_name"], f["fitting_type"], f["fitting_type_source"]),
                         ("MY_CUSTOM_BEND", "ELBOW", "xdata_tag"))
        self.assertIsNone(f["resolved_profile_prefix"])
        self.assertEqual(f["profile"], "DEFAULT")
        self.assertEqual(f["status"], "OK", f["issues"])

    def test_ordinary_block_is_not_a_fitting(self):
        r = rep("not-a-fitting")
        self.assertEqual(r["fittings"], [])

    def test_unsupported_entities_on_path_layer_are_reported_not_hidden(self):
        r = rep("unsupported-path-entity")
        self.assertEqual(len(r["paths"]), 1)
        w = [x for x in r["warnings"] if x["code"] == "UNSUPPORTED_PATH_ENTITY"]
        self.assertEqual(len(w), 2)
        self.assertTrue(any("CIRCLE" in x["message"] for x in w))
        self.assertTrue(any("ARC" in x["message"] for x in w))

    def test_non_z_extrusion_is_warned(self):
        f = fit("extrusion-insert")
        self.assertIn("INSERT_EXTRUSION_NOT_Z", codes(f))
        self.assertEqual(f["extrusion"], [0.0, 0.0, -1.0])


class CandidatesAndJunctions(unittest.TestCase):
    def test_fitting_without_any_path(self):
        f = fit("no-path")
        self.assertEqual(f["status"], "NOT_COMPUTABLE")
        self.assertIsNone(f["junction"])
        self.assertEqual(f["connections"], [])
        self.assertEqual(f["connected_path_candidates"], [])
        self.assertIsNone(f["max_connection_error_mm"])
        self.assertIn("NO_JUNCTION", codes(f))

    def test_multiple_candidate_paths_are_ranked(self):
        f = fit("multi-candidates")
        cands = f["connected_path_candidates"]
        self.assertEqual(len(cands), 5)
        dist = [c["junction_distance"] for c in cands]
        self.assertEqual(dist, sorted(dist))
        self.assertEqual([c["relation"] for c in cands][:2], ["exact", "exact"])
        self.assertTrue(all(c["touches_junction"] for c in cands[:2]))
        self.assertEqual([c["relation"] for c in cands][2:], ["unrelated"] * 3)
        self.assertAlmostEqual(dist[2], 400.0, places=6)
        self.assertAlmostEqual(dist[3], 900.0, places=6)
        self.assertAlmostEqual(dist[4], math.hypot(7000, 7000), places=4)
        for c in cands:
            for key in ("handle", "min_distance", "nearest_point", "profile", "width", "min_vertex_distance",
                        "junction_distance", "touches_junction", "relation"):
                self.assertIn(key, c)
        self.assertEqual(f["status"], "OK", f["issues"])
        classes = sorted(j["classification"] for j in rep("multi-candidates")["junctions"])
        self.assertEqual(classes, ["CROSS", "ELBOW"])

    def test_junction_without_fitting_is_reported(self):
        r = rep("no-fitting")
        self.assertEqual(r["fittings"], [])
        j = r["junctions"][0]
        self.assertEqual(j["classification"], "ELBOW")
        self.assertEqual(j["fitting_count"], 0)
        self.assertIn("NO_FITTING_AT_JUNCTION", codes(j))
        self.assertEqual(j["status"], "WARN")

    def test_thresholds_are_written_into_every_report(self):
        th = rep("elbow-r0")["thresholds"]
        for key in ("connection_exact_mm", "connection_near_mm", "arm_corridor_extra_mm", "end_face_band_mm",
                    "coordinate_tolerance_mm", "orthogonal_angle_tolerance_rad", "connection_status_rule",
                    "relation_rule", "expected_point_definition", "actual_point_definition"):
            self.assertIn(key, th)
        self.assertEqual((th["connection_exact_mm"], th["connection_near_mm"]), (0.01, 1.0))


class SingleAndExport(unittest.TestCase):
    def test_single_report_is_scoped_to_the_selected_fitting(self):
        r = rep("elbow-r3", "single")
        self.assertEqual(r["mode"], "single")
        self.assertEqual(len(r["fittings"]), 1)
        self.assertEqual(r["fittings"][0]["status"], "OK")
        self.assertEqual(len(r["junctions"]), 1)
        self.assertEqual(r["counts"]["paths_in_report"], 2)
        used = {h for c in r["fittings"][0]["connections"] for h in c["straight_handles"]}
        self.assertEqual({g["handle"] for g in r["generated_geometry"]}, used)
        self.assertEqual({p["handle"] for p in r["paths"]}, {c["handle"] for c in r["fittings"][0]["connected_path_candidates"]})

    def test_export_is_a_pure_data_dump(self):
        r = rep("readonly", "export")
        self.assertEqual(len(r["fittings"]), 1)
        f = r["fittings"][0]
        self.assertNotIn("connections", f)
        self.assertNotIn("junction", f)
        self.assertEqual(r["junctions"], [])
        self.assertEqual(len(r["paths"]), 4)
        self.assertEqual(f["xdata_raw"][0]["value"], "CROSS")
        self.assertTrue(all(len(p["vertices"]) == 2 for p in r["paths"]))
        self.assertEqual(len(r["generated_geometry"]), 12)
        self.assertEqual(ad.analyze(r)["fitting_types"], {"CROSS": 1})


class Escaping(unittest.TestCase):
    NASTY = "we" + '"' + "ird,prof" + "\\" + "x 中文"

    def test_json_escaping_roundtrip(self):
        r = rep("escape")                                   # json.load succeeded => syntactically valid
        self.assertEqual({p["profile"] for p in r["paths"]}, {self.NASTY})
        raw = next(x for x in r["paths"][0]["xdata_raw"] if str(x["value"]).startswith("PROFILE="))
        self.assertEqual(raw["value"], "PROFILE=" + self.NASTY)
        self.assertIn(self.NASTY, r["fittings"][0]["issues"][0]["detail"])
        text = next((ROOT / "escape" / "all").glob("*.json")).read_text(encoding="utf-8")
        self.assertIn('we\\"ird,prof\\\\x', text)             # quote and backslash escaped on disk
        text.encode("utf-8")

    def test_csv_escaping_roundtrip(self):
        path = next((ROOT / "escape" / "all").glob("*.csv"))
        rows = read_csv(path, dict_rows=False)
        header = rows[0]
        self.assertEqual(header[:19], ["drawing", "handle", "object_type", "block_name", "fitting_type", "profile",
                                       "width", "x", "y", "z", "scale_x", "scale_y", "rotation_deg", "junction_x",
                                       "junction_y", "degree", "classification", "max_connection_error_mm", "status"])
        self.assertTrue(all(len(r) == len(header) for r in rows), "ragged CSV rows")
        by = [dict(zip(header, r)) for r in rows[1:]]
        self.assertEqual({r["profile"] for r in by if r["object_type"] == "PATH"}, {self.NASTY})
        self.assertEqual(sum(1 for r in by if r["object_type"] == "FITTING"), 1)
        fit_row = next(r for r in by if r["object_type"] == "FITTING")
        self.assertIn("FITTING_PROFILE_MISMATCH", fit_row["issues"])
        self.assertEqual(fit_row["fitting_type"], "ELBOW")
        self.assertEqual(fit_row["status"], "FAIL")

    def test_csv_columns_for_a_normal_run(self):
        path = next((ROOT / "elbow-r1" / "all").glob("*.csv"))
        rows = read_csv(path)
        f = next(r for r in rows if r["object_type"] == "FITTING")
        self.assertEqual((f["block_name"], f["fitting_type"], f["profile"], f["width"]),
                         ("SCADA_V2$SCADA_TRAY_ELBOW_V2", "ELBOW", "SCADA_V2", "150"))
        self.assertAlmostEqual(float(f["rotation_deg"]), 90.0, places=6)
        self.assertEqual((f["classification"], f["degree"], f["status"], f["directions"]), ("ELBOW", "2", "OK", "W;N"))
        self.assertAlmostEqual(float(f["scale_x"]), 0.5, places=8)

    def test_txt_report_is_human_readable(self):
        text = next((ROOT / "takeoff-error" / "all").glob("*.txt")).read_text(encoding="utf-8")
        for token in ("Router diagnostic report", "FITTING ", "arm E", "arm N", "translation fit", "hint:",
                      "[FAIL] CONNECTION_MISMATCH", "PATH ", "no drawing changes"):
            self.assertIn(token, text)


class AnalyzerOnRealOutput(unittest.TestCase):
    def test_analyzer_runs_on_every_engine_report(self):
        for scene in er.SCENES:
            for mode_dir in (ROOT / scene).iterdir():
                with self.subTest(scene=scene, mode=mode_dir.name):
                    res = ad.analyze(er.latest_json(ROOT, scene, mode_dir.name))
                    ad.format_text(res)

    def test_analyzer_on_the_elbow_scene(self):
        res = ad.analyze(rep("offset-error"))
        self.assertEqual(res["fitting_types"], {"ELBOW": 1})
        self.assertEqual(res["largest_connection_error"]["error_mm"], 5.0)
        self.assertEqual(res["status_counts"], {"FAIL": 1})


if __name__ == "__main__":
    unittest.main()


def unit_close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class CurvedElbowOpenings(unittest.TestCase):
    """Regression: a curved ELBOW block (ARC + LINE, stubs, rungs) must be judged by its OPENINGS,
    not by its farthest point.  All numbers below come from the harness constants, not from the tool."""

    R, CC, CT, ST = 576.0, 622.9333333333, 17.0666666667, 68.2666666667
    S = 0.48159249

    def block(self, scene):
        return rep(scene)["blocks"][0]

    def test_block_local_geometry_listing(self):
        b = self.block("curved-r1")
        self.assertEqual(b["block_origin"], [0.0, 0.0])
        self.assertEqual(len(b["segments"]), 16)                         # duplicates removed
        self.assertEqual(len(b["arcs"]), 4)
        self.assertEqual(sorted(round(a["radius"], 3) for a in b["arcs"]), [256.0, 273.067, 878.933, 896.0])
        for a in b["arcs"]:
            self.assertEqual(a["center"], [0.0, 0.0])
            self.assertAlmostEqual(a["start_angle_deg"], 270.0, places=6)
            self.assertAlmostEqual(a["end_angle_deg"] % 360.0, 0.0, places=6)
        self.assertEqual(b["bbox_local"]["min"][:2], [-self.ST, -896.0])
        self.assertAlmostEqual(b["bbox_local"]["max"][0], 896.0, places=4)
        self.assertAlmostEqual(b["bbox_local"]["max"][1], self.ST, places=4)

    def test_two_openings_from_rail_end_caps(self):
        b = self.block("curved-r1")
        self.assertEqual(len(b["openings"]), 2)
        west = next(o for o in b["openings"] if o["outward_normal"] == [-1.0, 0.0])
        north = next(o for o in b["openings"] if o["outward_normal"] == [0.0, 1.0])
        self.assertTrue(unit_close(west["opening_center"], [-self.ST, -self.R], 1e-3))
        self.assertTrue(unit_close(north["opening_center"], [self.R, self.ST], 1e-3))
        for o in (west, north):
            self.assertAlmostEqual(o["width_rail_center_to_rail_center"], self.CC, places=3)
            self.assertAlmostEqual(o["width_outer_edge_to_outer_edge"], self.CC + self.CT, places=3)
            self.assertAlmostEqual(o["width_inner_edge_to_inner_edge"], self.CC - self.CT, places=3)
            self.assertAlmostEqual(o["rail_end_cap_length"], self.CT, places=3)
            for rail in o["rails"]:
                oe, ie, rc = rail["outer_edge_point"], rail["inner_edge_point"], rail["rail_center_point"]
                self.assertTrue(unit_close(rc, [(oe[0] + ie[0]) / 2, (oe[1] + ie[1]) / 2], 1e-6))
                self.assertAlmostEqual(math.dist(oe, ie), self.CT, places=3)
        # west opening: rail centres at y = -576 +- cc/2, outer edges beyond them, inner edges toward the centre
        ys = sorted(r["rail_center_point"][1] for r in west["rails"])
        self.assertAlmostEqual(ys[0], -self.R - self.CC / 2, places=3)
        self.assertAlmostEqual(ys[1], -self.R + self.CC / 2, places=3)
        low = min(west["rails"], key=lambda r: r["rail_center_point"][1])
        self.assertLess(low["outer_edge_point"][1], low["inner_edge_point"][1])
        self.assertLess(low["outer_edge_point"][1], low["rail_center_point"][1])
        # the two opening axes cross at the tangent-line corner (576,-576); pivot is the arc centre (0,0)
        self.assertTrue(unit_close(b["derived_joint"], [self.R, -self.R], 1e-3))
        self.assertLess(b["derived_joint_axis_rms"], 1e-3)

    def test_correct_curved_elbow_has_zero_error(self):
        f = fit("curved-r1")
        self.assertEqual(f["opening_method"], "derived_opening")
        self.assertEqual(f["status"], "OK", f["issues"])
        self.assertEqual(f["junction"]["directions"], ["W", "S"])
        for c in f["connections"]:
            self.assertEqual(c["status"], "EXACT")
            self.assertLess(c["error_mm"], 1e-5)
            self.assertIsNotNone(c["opening_id"])
            self.assertEqual(len(c["rail_center_differences_mm"]), 2)
            self.assertTrue(all(abs(d) < 1e-5 for d in c["rail_center_differences_mm"]), c["rail_center_differences_mm"])
            self.assertAlmostEqual(c["opening_distance_from_junction_mm"], (self.R + self.ST) * self.S, places=4)
            self.assertAlmostEqual(c["straight_start_distance_from_junction_mm"], (self.R + self.ST) * self.S, places=4)
        self.assertTrue(unit_close(f["junction_minus_derived_joint_block"], [0.0, 0.0], 1e-3))

    def test_pivot_not_at_origin_is_still_exact_when_placed_from_the_joint(self):
        f = fit("curved-r3-shifted-pivot")
        self.assertEqual(f["status"], "OK", f["issues"])
        self.assertLess(f["max_connection_error_mm"], 1e-5)
        b = self.block("curved-r3-shifted-pivot")
        self.assertTrue(unit_close(b["derived_joint"], [-686.7333333333 + self.R, 521.0 - self.R], 1e-3))

    def test_farthest_point_decoy_is_not_an_opening(self):
        f = fit("curved-decoy")
        self.assertEqual(f["status"], "OK", f["issues"])
        self.assertLess(f["max_connection_error_mm"], 1e-5)
        b = self.block("curved-decoy")
        self.assertLess(b["bbox_local"]["min"][0], -self.ST - 399.0)     # decoy sticks out 400 beyond the caps
        self.assertEqual(len(b["openings"]), 2)
        west = next(o for o in b["openings"] if o["outward_normal"] == [-1.0, 0.0])
        self.assertTrue(unit_close(west["opening_center"], [-self.ST, -self.R], 1e-3))
        # an extreme-point metric would have measured the decoy: it is much farther than the opening
        ext = f["fitting_geometry_extent_from_junction_mm"]
        open_dist = f["connections"][0]["opening_distance_from_junction_mm"]
        self.assertGreater(max(v for v in ext.values() if v is not None), open_dist + 300.0 * self.S)

    def test_router_style_origin_assumption_is_a_pure_translation(self):
        """The situation seen in TEST.dwg: block pivot != origin but placement assumes joint (576,-576)."""
        f = fit("curved-router-assumption")
        self.assertEqual(f["status"], "FAIL")
        t = f["translation_fit"]
        self.assertTrue(unit_close(t["in_block_coords"], [-686.7333333333, 521.0], 1e-3), t["in_block_coords"])
        self.assertAlmostEqual(t["magnitude_mm"], math.hypot(686.7333333333, 521.0) * self.S, places=3)
        self.assertLess(t["rms_lateral_residual_mm"], 1e-4)
        self.assertTrue(all(abs(p["axial_residual_mm"]) < 1e-4 for p in t["per_arm"]))
        for c in f["connections"]:
            self.assertEqual(c["status"], "MISMATCH")
            self.assertAlmostEqual(c["error_mm"], t["magnitude_mm"], places=3)
        self.assertTrue(unit_close(f["junction_in_block_coords"], [self.R, -self.R], 1e-3))
        self.assertTrue(unit_close(f["derived_joint_block"], [-686.7333333333 + self.R, 521.0 - self.R], 1e-3))
        self.assertTrue(unit_close(f["junction_minus_derived_joint_block"], [686.7333333333, -521.0], 1e-3))
        self.assertTrue(any(h.startswith("TRANSLATION_EQUALS_JOINT_DELTA") for h in t["hints"]))
        self.assertTrue(any(h.startswith("PLACEMENT_OFFSET") for h in t["hints"]))

    def test_takeoff_at_arc_tangent_leaves_only_the_stub_as_axial_residual(self):
        f = fit("curved-takeoff-at-tangent")
        t = f["translation_fit"]
        self.assertLess(t["magnitude_mm"], 1e-4)
        for p in t["per_arm"]:
            self.assertAlmostEqual(p["axial_residual_mm"], self.ST * self.S, places=3)
            self.assertLess(abs(p["lateral_residual_mm"]), 1e-4)
        for c in f["connections"]:
            self.assertAlmostEqual(c["error_mm"], self.ST * self.S, places=3)
            self.assertAlmostEqual(c["axial_error_mm"], self.ST * self.S, places=3)
        self.assertTrue(any(h.startswith("ARM_LENGTH_OR_TAKEOFF") for h in t["hints"]))
        self.assertFalse(any(h.startswith("PLACEMENT_OFFSET") for h in t["hints"]))

    def test_wrong_rotation_is_reported_as_missing_opening_not_as_a_distance(self):
        f = fit("curved-rot-error")
        self.assertEqual(f["status"], "FAIL")
        self.assertIn("ARM_WITHOUT_OPENING", codes(f))
        self.assertIn("OPENING_WITHOUT_ARM", codes(f))
        self.assertIn("NO_OPENING", [c["status"] for c in f["connections"]])


class AmbiguityAndShortSegments(unittest.TestCase):
    """Regression for TEST_V1.dwg: stacked-variant blocks and fittings closer than their takeoffs must not give FAIL by guesswork."""

    def test_stacked_openings_are_ambiguous_not_guessed(self):
        f = fit("stacked-variants")
        self.assertEqual(f["opening_method"], "derived_opening")
        self.assertEqual(sorted(c["status"] for c in f["connections"]), ["AMBIGUOUS_OPENING", "AMBIGUOUS_OPENING"])
        self.assertTrue(all(c["error_mm"] is None and c["opening_id"] is None for c in f["connections"]))
        self.assertEqual(codes(f).count("OPENING_AMBIGUOUS"), 2)
        self.assertNotIn("OPENING_WITHOUT_ARM", codes(f))
        self.assertNotIn("CONNECTION_MISMATCH", codes(f))
        self.assertEqual(f["status"], "WARN")
        b = rep("stacked-variants")["blocks"][0]
        self.assertTrue(any(o["ambiguous"] for o in b["openings"]))

    def test_no_derivable_opening_falls_back_with_a_warning(self):
        f = fit("no-caps")
        self.assertEqual(f["opening_method"], "extreme_face_fallback")
        self.assertIn("OPENING_NOT_DERIVED", codes(f))
        self.assertEqual(f["status"], "WARN")
        self.assertTrue(all(c["method"] == "extreme_face_fallback" for c in f["connections"]))

    def test_unique_openings_are_not_flagged_ambiguous(self):
        for scene in ("elbow-r0", "tee-r0", "cross", "curved-r1", "curved-decoy"):
            for o in rep(scene)["blocks"][0]["openings"]:
                self.assertFalse(o["ambiguous"], scene)

    def test_segment_shorter_than_two_takeoffs_has_no_straight_and_says_so(self):
        r = rep("short-segment")
        by_dir = {}
        for f in r["fittings"]:
            for c in f["connections"]:
                by_dir[(f["junction"]["junction_y"], c["direction"])] = c
        n_arm = by_dir[(0.0, "N")]
        s_arm = by_dir[(500.0, "S")]
        for c in (n_arm, s_arm):
            self.assertEqual(c["status"], "NOT_COMPUTABLE")
            self.assertAlmostEqual(c["next_node_distance_mm"], 500.0, places=6)
            self.assertIn("between this junction and the next PATH node 500", c["reason"])
        for key in ((0.0, "E"), (500.0, "E")):
            self.assertEqual(by_dir[key]["status"], "EXACT")                 # the far Straights are NOT mistaken for it
        for f in r["fittings"]:
            self.assertEqual(f["status"], "WARN")
            self.assertNotIn("CONNECTION_MISMATCH", codes(f))
