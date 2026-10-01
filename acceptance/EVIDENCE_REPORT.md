# SCADA_V2 @ 300 mm - Integration Acceptance, evidence report (engine part)

Width scope: **300 mm only. Other widths (150 / 450 / 600): NOT VERIFIED.**
Router: committed `5669d5a` (BASE_OFFSET (110.7333 55.0), TAKEOFF 644.2667), Router source SHA-256 `1a1792335f25b7a9cb888285099c50fbfde12c247643bafb59305d8b2fb6f70e`, not modified.
Acceptance DWG: `acceptance/scada_v2_300_acceptance.dwg` SHA-256 `b5c4cb9c9b83c30345355ba7f0b082e9e049a75ace8d0a339e1735bf1c3d46be` (unchanged by the analysis: after = `b5c4cb9c9b83c30345355ba7f0b082e9e049a75ace8d0a339e1735bf1c3d46be`).

## A. CONFIRMED (ran, with evidence in acceptance/evidence/)
- Drawing built by the Router in accoreconsole on a blank scratch drawing, saved as a new DWG, reopened as a scratch copy for analysis.
- 12 cases: A (4 Elbow orientations W+N, W+S, E+S, E+N), B (4 Tee: branch N, S, W, E), C (Cross, W/E/N/S), D (chain Elbow-Tee-Elbow-Cross in one routing),
  E (E,N,W,N turns, long and short 800 mm middle segments).
- Joints (each fitting arm): 47 total, 47 PASS; per joint: gap, overlap, axial residual, lateral error, rail-centre differences,
  insertion check (derived joint vs designed node), trim check (Straight start measured from entity vertices vs block-derived opening distance).
  Tolerance 0.01 mm. Largest |gap| 3.2e-5 mm, no overlap > 0, lateral <= 1.6e-5 mm. See joints.csv / joints.json.
- Entity accounting: 444 entities (SSGET count 444), Router-generated 425, PATH 19;
  matched 444, unmatched 0, duplicates 0, expected-but-missing 0.
  classes: {'STRAIGHT rung matched': 326, 'STRAIGHT rail matched': 80, 'FITTING matched': 19, 'PATH matched': 19}. All in layout(s) {'Model': 444}.
- Item 8: Tee and Cross cases B1-B4, C1 are entity-for-entity identical (type, layer, block, XDATA tag, vertices, insert, rotation, scale; 1e-5) between
  the Router at `5669d5a^` (old Elbow config) and `5669d5a`.
- Router regression `tools/run_tests.py`: 134 passed, 0 failed.

## B. FAILED
- No joint, entity or regression failure.
- Observation (not a joint failure): every rung stops 10 mm short of each rail inner edge (rung half length 130 = width/2 - thickness, rail inner edge at 140 because
  rails are centred on +-width/2). Router ladder generator, outside this acceptance scope; listed in the GUI checklist for a human decision.

## C. NOT VERIFIED
- SAVE / REOPEN in the AutoCAD GUI (item 9): PENDING HUMAN GUI.
- GUI visual agreement with engine evidence (item 10): PENDING HUMAN GUI.
- SCADA_V2 150 mm, 450 mm, 600 mm (BASE_OFFSET / TAKEOFF are block-unit calibrations at 300 mm; nothing here shows they hold at other widths).
- Expected rung positions follow the Router's documented rule (count floor(len/250), first 125, anchored at the segment start; either end accepted per edge) - a Router-vs-Router
  consistency check, not an independent standard.
- Opening distances come from the diagnostics' block-geometry model (validated by curved-Elbow tests and the TEST.dwg analysis), not from a separate tool.

## D. GUI checklist
`acceptance/GUI_CHECKLIST.md` (items 9 and 10, joint IDs and handles from joints.json).

Reproduce: `python acceptance/run_acceptance.py [--rebuild]`, then `python acceptance/make_gui_checklist.py`.
