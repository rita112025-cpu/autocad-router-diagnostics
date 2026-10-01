# GUI ACCEPTANCE CHECKLIST - SCADA_V2 @ 300 mm

**Width scope: 300 mm only. Other widths: NOT VERIFIED.** Engine evidence: `acceptance/evidence/` (joints.json, entity_accounting.json,
diagnostics_all.json). Items 1-8 are engine-judged; **items 9 and 10 are `PENDING HUMAN GUI`** until you fill this in.

Acceptance drawing (do NOT edit the original): `acceptance/scada_v2_300_acceptance.dwg`  (SHA-256 `b5c4cb9c9b83c30345355ba7f0b082e9e049a75ace8d0a339e1735bf1c3d46be`)
Work on a COPY: `copy acceptance\scada_v2_300_acceptance.dwg acceptance\scada_v2_300_acceptance_GUI.dwg` and open the copy.

Engine facts to compare with: 19 fittings, 19 PATH, 406 generated Straight polylines
(rails + rungs), total entities **444** (19 PATH + 19 INSERT + 80 rails + 326 rungs), all in Model space, 47 joints (arms) all PASS.

How to read values in the GUI without changing anything: type in the command line `(entget (handent "HANDLE"))` and press Enter (read-only),
or use `LIST` on the object. Diagnostics (`CTRDIAGALL`, read-only) writes `output/ctrdiag_*_all.json`.

---------------------------------------------------------------------------------------------------

## ITEM 9 - SAVE / REOPEN keeps the geometry unchanged   (status: PENDING HUMAN GUI)

| # | Step | Look at | Expected | Record | PASS / FAIL | Screenshot |
|---|---|---|---|---|---|---|
| 9.1 | Open `scada_v2_300_acceptance_GUI.dwg` (copy). `APPLOAD` `autocad_router_diagnostics.lsp`, run `CTRDIAGALL`. | command line, `output/` | 3 files written, `fittings 19`, no error | JSON path: ______ (call it BEFORE.json) | | `9_1_before_ctrdiagall.png` |
| 9.2 | Press `Ctrl+A` (select all, Model space). | command line | `444 found` | found = ____ | | `9_2_select_all_before.png` |
| 9.3 | Record these handles with `(entget (handent "H"))`: `3FC`, `3FD`, `3FE`, `3FF` (full list in diagnostics_all.json) | insert point, rotation, scale of each | equal to the "Fitting" lines of item 10 | ______ | | `9_3_handles_before.png` |
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

#### A1_W+N (Elbow, W+N)

- Fitting: handle `40E` SCADA_V2$SCADA_TRAY_ELBOW_V2  insert (53.3283, 26.4876)  rot 0.0 deg  scale 0.481592

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `A1_W+N/N2/W` | W+N | opening (-310.2740, 0.0000) | Straight end (-310.2740, 0.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `A1_W+N/N2/N` | W+N | opening (-0.0000, 310.2740) | Straight end (0.0000, 310.2740) | gap/overlap 0.00002 / 0.00000 | | |

Additional Elbow orientation for comparison (screenshot `10_1b_elbow_A3.png`), design junction (20000, 0), arms E+S:

#### A3_E+S (Elbow, E+S)

- Fitting: handle `40C` SCADA_V2$SCADA_TRAY_ELBOW_V2  insert (19946.6717, -26.4876)  rot 180.0 deg  scale 0.481592

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `A3_E+S/N2/E` | E+S | opening (20310.2740, 0.0000) | Straight end (20310.2740, 0.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `A3_E+S/N2/S` | E+S | opening (20000.0000, -310.2740) | Straight end (20000.0000, -310.2740) | gap/overlap 0.00002 / 0.00000 | | |

Record: visual gap? Y / N   visual overlap? Y / N   rail centre lines continuous? Y / N   PASS / FAIL: ______

### 10.2 One Tee (screenshot `10_2_tee_B1.png`)
Case `B1_TEE_branch_N`, design junction (40500, 0): main incoming W, main outgoing E, branch N.

#### B1_TEE_branch_N

- Fitting: handle `40A` SCADA_V2$SCADA_TRAY_TEE_V2  insert (40500.0000, -160.7143)  rot 0.0 deg  scale 0.945378

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `B1_TEE_branch_N/N2/E` | E+W+N | opening (40907.1429, 0.0000) | Straight end (40907.1429, 0.0000) | gap/overlap 0.00003 / 0.00000 | | |
| `B1_TEE_branch_N/N2/W` | E+W+N | opening (40092.8571, 0.0000) | Straight end (40092.8571, 0.0000) | gap/overlap 0.00003 / 0.00000 | | |
| `B1_TEE_branch_N/N2/N` | E+W+N | opening (40500.0000, 407.1429) | Straight end (40500.0000, 407.1429) | gap/overlap 0.00003 / 0.00000 | | |

Record: gap / overlap on the three arms? ______   PASS / FAIL: ______

### 10.3 One Cross (screenshot `10_3_cross_C1.png`)
Case `C1_CROSS`, design junction (65000, 0): W, E, N, S.

#### C1_CROSS

- Fitting: handle `406` SCADA_V2$SCADA_TRAY_CROSS_V2  insert (65000.0000, -160.7143)  rot 0.0 deg  scale 0.945378

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `C1_CROSS/N3/E` | E+W+N+S | opening (65407.1429, 0.0000) | Straight end (65407.1429, 0.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `C1_CROSS/N3/W` | E+W+N+S | opening (64592.8571, 0.0000) | Straight end (64592.8571, 0.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `C1_CROSS/N3/N` | E+W+N+S | opening (65000.0000, 407.1429) | Straight end (65000.0000, 407.1429) | gap/overlap 0.00000 / 0.00000 | | |
| `C1_CROSS/N3/S` | E+W+N+S | opening (65000.0000, -407.1429) | Straight end (65000.0000, -407.1429) | gap/overlap 0.00000 / 0.00000 | | |

Record: gap / overlap on the four arms? ______   PASS / FAIL: ______

### 10.4 One multi-junction chain (screenshots `10_4_chain_overview.png`, `10_4_chain_N2.png` ... `10_4_chain_N7.png`)
Case `D1_CHAIN` (route: Straight - Elbow(0..4000,10000) - Straight - Tee(4000,14000) - Straight - Elbow(4000,18000) - Straight - Cross(9000,18000) - Straight).
First `ZOOM` window (-1000, 9000) to (13000, 22000) for the overview, then each junction.

#### D1 node N2 - Elbow at (4000, 10000)

- Fitting: handle `404` SCADA_V2$SCADA_TRAY_ELBOW_V2  insert (4053.3283, 10026.4876)  rot 0.0 deg  scale 0.481592

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `D1_CHAIN/N2/W` | W+N | opening (3689.7260, 10000.0000) | Straight end (3689.7260, 10000.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `D1_CHAIN/N2/N` | W+N | opening (4000.0000, 10310.2740) | Straight end (4000.0000, 10310.2740) | gap/overlap 0.00002 / 0.00000 | | |

#### D1 node N3 - Tee at (4000, 14000)

- Fitting: handle `403` SCADA_V2$SCADA_TRAY_TEE_V2  insert (3839.2857, 14000.0000)  rot 270.0 deg  scale 0.945378

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `D1_CHAIN/N3/E` | E+N+S | opening (4407.1429, 14000.0000) | Straight end (4407.1429, 14000.0000) | gap/overlap 0.00003 / 0.00000 | | |
| `D1_CHAIN/N3/N` | E+N+S | opening (4000.0000, 14407.1429) | Straight end (4000.0000, 14407.1429) | gap/overlap 0.00003 / 0.00000 | | |
| `D1_CHAIN/N3/S` | E+N+S | opening (4000.0000, 13592.8571) | Straight end (4000.0000, 13592.8571) | gap/overlap 0.00003 / 0.00000 | | |

#### D1 node N4 - Elbow at (4000, 18000)

- Fitting: handle `405` SCADA_V2$SCADA_TRAY_ELBOW_V2  insert (3946.6717, 17973.5124)  rot 180.0 deg  scale 0.481592

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `D1_CHAIN/N4/E` | E+S | opening (4310.2740, 18000.0000) | Straight end (4310.2740, 18000.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `D1_CHAIN/N4/S` | E+S | opening (4000.0000, 17689.7260) | Straight end (4000.0000, 17689.7260) | gap/overlap 0.00002 / 0.00000 | | |

#### D1 node N7 - Cross at (9000, 18000)

- Fitting: handle `402` SCADA_V2$SCADA_TRAY_CROSS_V2  insert (9000.0000, 17839.2857)  rot 0.0 deg  scale 0.945378

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `D1_CHAIN/N7/E` | E+W+N+S | opening (9407.1429, 18000.0000) | Straight end (9407.1429, 18000.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `D1_CHAIN/N7/W` | E+W+N+S | opening (8592.8571, 18000.0000) | Straight end (8592.8571, 18000.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `D1_CHAIN/N7/N` | E+W+N+S | opening (9000.0000, 18407.1429) | Straight end (9000.0000, 18407.1429) | gap/overlap 0.00000 / 0.00000 | | |
| `D1_CHAIN/N7/S` | E+W+N+S | opening (9000.0000, 17592.8571) | Straight end (9000.0000, 17592.8571) | gap/overlap 0.00000 / 0.00000 | | |

Record: any accumulated offset along the chain (the last Cross still on the design junction)? Y / N   PASS / FAIL: ______

### 10.5 Consecutive turns, short middle segments (screenshot `10_5_turns_E2.png`)
Case `E2_TURNS_short`, route E,N,W,N with 800 mm middle segments (each Straight is only ~179.5 mm long).

#### E2_TURNS_short

- Fitting: handle `3FC` SCADA_V2$SCADA_TRAY_ELBOW_V2  insert (12053.3283, 30026.4876)  rot 0.0 deg  scale 0.481592
- Fitting: handle `3FD` SCADA_V2$SCADA_TRAY_ELBOW_V2  insert (11973.5124, 30853.3283)  rot 90.0 deg  scale 0.481592
- Fitting: handle `3FE` SCADA_V2$SCADA_TRAY_ELBOW_V2  insert (11226.4876, 30746.6717)  rot 270.0 deg  scale 0.481592

| Joint ID | Orientation | Expected (engine) | Straight end (engine) | Expected gap / overlap | GUI observed value | PASS / FAIL |
|---|---|---|---|---|---|---|
| `E2_TURNS_short/N2/E` | E+N | opening (11510.2740, 30800.0000) | Straight end (11510.2740, 30800.0000) | gap/overlap 0.00002 / 0.00000 | | |
| `E2_TURNS_short/N2/N` | E+N | opening (11200.0000, 31110.2740) | Straight end (11200.0000, 31110.2740) | gap/overlap 0.00000 / 0.00000 | | |
| `E2_TURNS_short/N4/W` | W+N | opening (11689.7260, 30000.0000) | Straight end (11689.7260, 30000.0000) | gap/overlap 0.00000 / 0.00000 | | |
| `E2_TURNS_short/N4/N` | W+N | opening (12000.0000, 30310.2740) | Straight end (12000.0000, 30310.2740) | gap/overlap 0.00002 / 0.00000 | | |
| `E2_TURNS_short/N5/W` | W+S | opening (11689.7260, 30800.0000) | Straight end (11689.7260, 30800.0000) | gap/overlap 0.00002 / 0.00000 | | |
| `E2_TURNS_short/N5/S` | W+S | opening (12000.0000, 30489.7260) | Straight end (12000.0000, 30489.7260) | gap/overlap 0.00000 / 0.00000 | | |

Record: Straights between the elbows visible and connected? Y / N   PASS / FAIL: ______

---------------------------------------------------------------------------------------------------

## Observation to look at once (not a joint criterion)
Every rung of every Straight stops **10 mm short of each rail inner edge** (rung half length 130 mm, rail inner edge 140 mm). This is the Router ladder
generator, unrelated to joints; look at one Straight at high zoom and record whether you accept it: ACCEPT / REJECT: ______  (screenshot `10_6_rung_gap.png`).

## Sign-off
Item 9: ______   Item 10: ______   Tester: ______   Date: ______
