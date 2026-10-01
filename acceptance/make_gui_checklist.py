"""Generate acceptance/GUI_CHECKLIST.md (items 9 and 10) from the engine evidence, so every GUI check names the
joint IDs / handles / expected numbers that appear in acceptance/evidence/joints.json."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
J = json.loads((HERE / "evidence" / "joints.json").read_text(encoding="utf-8"))
D = json.loads((HERE / "evidence" / "diagnostics_all.json").read_text(encoding="utf-8"))
S = json.loads((HERE / "evidence" / "summary.json").read_text(encoding="utf-8"))
FIT = {f["handle"]: f for f in D["fittings"]}


def joints_of(case, node=None):
    return [j for j in J if j["case_id"] == case and (node is None or "/N%d/" % node in j["joint_id"])]


def fit_line(h):
    f = FIT[h]
    return "handle `%s` %s  insert (%.4f, %.4f)  rot %.1f deg  scale %.6f" % (
        h, f["raw_block_name"], f["insert_x"], f["insert_y"], f["rotation_deg"], f["scale_x"])


def joint_rows(js):
    out = []
    for j in js:
        out.append("| `%s` | %s | opening (%.4f, %.4f) | Straight end (%.4f, %.4f) | gap/overlap %.5f / %.5f | | |" % (
            j["joint_id"], j["orientation"], j["expected_point"][0], j["expected_point"][1], j["actual_point"][0], j["actual_point"][1],
            j["gap_mm"], j["overlap_mm"]))
    return "\n".join(out)


def block(title, js):
    handles = sorted({j["fitting_handle"] for j in js})
    lines = ["#### " + title, ""]
    for h in handles:
        lines.append("- Fitting: " + fit_line(h))
    lines += ["", "| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |",
              "|---|---|---|---|---|---|---|", joint_rows(js), ""]
    return "\n".join(lines)


a1 = joints_of("A1_W+N")
a3 = joints_of("A3_E+S")
b1 = joints_of("B1_TEE_branch_N")
c1 = joints_of("C1_CROSS")
d1_n = {n: joints_of("D1_CHAIN", n) for n in (2, 3, 4, 7)}
e2 = joints_of("E2_TURNS_short")

md = f"""# GUI ACCEPTANCE CHECKLIST - SCADA_V2 @ 300 mm

**Width scope: 300 mm only. Other widths: NOT VERIFIED.** Engine evidence: `acceptance/evidence/` (joints.json, entity_accounting.json,
diagnostics_all.json). Items 1-8 are engine-judged; **items 9 and 10 are `PENDING HUMAN GUI`** until you fill this in.

Acceptance drawing (do NOT edit the original): `acceptance/scada_v2_300_acceptance.dwg`  (SHA-256 `{S['dwg_sha256_before']}`)
Work on a COPY: `copy acceptance\\scada_v2_300_acceptance.dwg acceptance\\scada_v2_300_acceptance_GUI.dwg` and open the copy.

Engine facts to compare with: {D['counts']['fittings']} fittings, {D['counts']['paths_in_drawing']} PATH, {D['counts']['straights_in_drawing']} generated Straight polylines
(rails + rungs), total entities **444** (19 PATH + 19 INSERT + 80 rails + 326 rungs), all in Model space, 47 joints (arms) all PASS.

How to read values in the GUI without changing anything: type in the command line `(entget (handent "HANDLE"))` and press Enter (read-only),
or use `LIST` on the object. Diagnostics (`CTRDIAGALL`, read-only) writes `output/ctrdiag_*_all.json`.

---------------------------------------------------------------------------------------------------

## ITEM 9 - SAVE / REOPEN keeps the geometry unchanged   (status: PENDING HUMAN GUI)

| # | Step | Look at | Expected | Record | PASS / FAIL | Screenshot |
|---|---|---|---|---|---|---|
| 9.1 | Open `scada_v2_300_acceptance_GUI.dwg` (copy). `APPLOAD` `autocad_router_diagnostics.lsp`, run `CTRDIAGALL`. | command line, `output/` | 3 files written, `fittings 19`, no error | JSON path: ______ (call it BEFORE.json) | | `9_1_before_ctrdiagall.png` |
| 9.2 | Press `Ctrl+A` (select all, Model space). | command line | `444 found` | found = ____ | | `9_2_select_all_before.png` |
| 9.3 | Record these handles with `(entget (handent "H"))`: {', '.join('`%s`' % h for h in sorted(FIT)[:4])} (full list in diagnostics_all.json) | insert point, rotation, scale of each | equal to the "Fitting" lines of item 10 | ______ | | `9_3_handles_before.png` |
| 9.4 | `SAVE` (Ctrl+S) and note whether a prompt appeared. | title bar | file saved | prompt: ____ | | `9_4_save.png` |
| 9.5 | Close the drawing (`CLOSE`). | | | | | |
| 9.6 | Reopen the same file. | title bar | opens, no recover / audit message | message: ____ | | `9_6_reopen.png` |
| 9.7 | `Ctrl+A` again. | command line | `444 found` (same as 9.2) | found = ____ | | `9_7_select_all_after.png` |
| 9.8 | `CTRDIAGALL` again (AFTER.json), then run `python acceptance/compare_reports.py BEFORE.json AFTER.json`. | terminal | `IDENTICAL`, exit code 0 | output: ______ | | `9_8_compare.png` |
| 9.9 | Re-check the same handles as 9.3 and the joints listed in item 10. | | unchanged | ______ | | `9_9_handles_after.png` |
| 9.10 | Entity / geometry unchanged? | | no entity added, removed or moved | | | |

Overall item 9:  PASS / FAIL  (circle)   Tester: ______  Date: ______

---------------------------------------------------------------------------------------------------

## ITEM 10 - GUI display agrees with the engine evidence   (status: PENDING HUMAN GUI)

For every joint: `ZOOM` so the joint fills the screen (a window about 1500 mm wide around the junction), turn the layer `SCADA-TRAY-PATH` on, and judge:
rails continue straight through the fitting stubs with **no visible gap and no visible overlap**; the two rails of the Straight and of the
fitting lie on the same centre lines; the PATH centre line meets the fitting joint. Then record the fitting's insertion point, rotation and scale
from `LIST` and compare to the engine numbers. Screenshot names are suggestions.

### 10.1 One Elbow joint (screenshot `10_1_elbow_A1.png`)
Junction (design) = (0, 0), arms W+N, case `A1_W+N`.

{block('A1_W+N (Elbow, W+N)', a1)}
Additional Elbow orientation for comparison (screenshot `10_1b_elbow_A3.png`), design junction (20000, 0), arms E+S:

{block('A3_E+S (Elbow, E+S)', a3)}
Record: visual gap? Y / N   visual overlap? Y / N   rail centre lines continuous? Y / N   PASS / FAIL: ______

### 10.2 One Tee (screenshot `10_2_tee_B1.png`)
Case `B1_TEE_branch_N`, design junction (40500, 0): main incoming W, main outgoing E, branch N.

{block('B1_TEE_branch_N', b1)}
Record: gap / overlap on the three arms? ______   PASS / FAIL: ______

### 10.3 One Cross (screenshot `10_3_cross_C1.png`)
Case `C1_CROSS`, design junction (65000, 0): W, E, N, S.

{block('C1_CROSS', c1)}
Record: gap / overlap on the four arms? ______   PASS / FAIL: ______

### 10.4 One multi-junction chain (screenshots `10_4_chain_overview.png`, `10_4_chain_N2.png` ... `10_4_chain_N7.png`)
Case `D1_CHAIN` (route: Straight - Elbow(0..4000,10000) - Straight - Tee(4000,14000) - Straight - Elbow(4000,18000) - Straight - Cross(9000,18000) - Straight).
First `ZOOM` window (-1000, 9000) to (13000, 22000) for the overview, then each junction.

{block('D1 node N2 - Elbow at (4000, 10000)', d1_n[2])}
{block('D1 node N3 - Tee at (4000, 14000)', d1_n[3])}
{block('D1 node N4 - Elbow at (4000, 18000)', d1_n[4])}
{block('D1 node N7 - Cross at (9000, 18000)', d1_n[7])}
Record: any accumulated offset along the chain (the last Cross still on the design junction)? Y / N   PASS / FAIL: ______

### 10.5 Consecutive turns, short middle segments (screenshot `10_5_turns_E2.png`)
Case `E2_TURNS_short`, route E,N,W,N with 800 mm middle segments (each Straight is only ~179.5 mm long).

{block('E2_TURNS_short', e2)}
Record: Straights between the elbows visible and connected? Y / N   PASS / FAIL: ______

---------------------------------------------------------------------------------------------------

## Observation to look at once (not a joint criterion)
Every rung of every Straight stops **{S.get('rung_gap_mm', 10.0):.0f} mm short of each rail inner edge** (rung half length 130 mm, rail inner edge 140 mm). This is the Router ladder
generator, unrelated to joints; look at one Straight at high zoom and record whether you accept it: ACCEPT / REJECT: ______  (screenshot `10_6_rung_gap.png`).

## Sign-off
Item 9: ______   Item 10: ______   Tester: ______   Date: ______
"""
(HERE / "GUI_CHECKLIST.md").write_text(md, encoding="utf-8")
print("written", HERE / "GUI_CHECKLIST.md", len(md))
