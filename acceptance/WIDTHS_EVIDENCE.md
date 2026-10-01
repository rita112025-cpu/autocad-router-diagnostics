# SCADA_V2 acceptance at 150 / 300 / 450 / 600 mm - engine evidence

Same cases and same checks as the 300 mm acceptance (items 1-8), one run per width: `ACC_WIDTH=<w> python acceptance/run_acceptance.py --rebuild`
(Router: committed `5669d5a` Elbow config, not modified; the only width-dependent design input is the E2 short-segment length = 2 x Elbow takeoff + 179.5 mm).
Tolerance 0.01 mm. Drawings: `acceptance/scada_v2_<w>_acceptance.dwg` (new files; analysis ran on scratch copies, SHA-256 unchanged).

| width | evidence | joints PASS | Elbow opening dist. mm | Tee/Cross opening dist. mm | max gap mm | max overlap mm | entities total/matched/unmatched/missing | Router regression pass/fail |
|---|---|---|---|---|---|---|---|---|
| 150 | acceptance/evidence_150/ | 47/47 | 155.137 | 203.571 | 1.6e-05 | 0 | 482/482/0/0 | 134/0 |
| 300 | acceptance/evidence/ | 47/47 | 310.274 | 407.143 | 3.2e-05 | 0 | 444/444/0/0 | 134/0 |
| 450 | acceptance/evidence_450/ | 47/47 | 465.411 | 610.714 | 4.7e-05 | 0 | 415/415/0/0 | 134/0 |
| 600 | acceptance/evidence_600/ | 47/47 | 620.548 | 814.286 | 6.3e-05 | 0 | 378/378/0/0 | 134/0 |

Per width: Tee and Cross cases B1-B4 / C1 are entity-for-entity identical between the Router at `5669d5a^` and `5669d5a`.
Openings scale with the width as the Router scales the block (Elbow 155.137 / 310.274 / 465.411 / 620.548 = 644.2667 x width / 622.9333).

## Still NOT verified by evidence
- GUI SAVE/REOPEN and GUI visual agreement at 150 / 450 / 600 mm (the user reported these widths tested OK; no evidence file exists for that).
- Other widths (e.g. 750 mm, non-preset widths) and non-uniform scale cases.
- Rung geometry (10 mm rung-to-rail gap) is unchanged at every width: rung half length = width/2 - 20 vs rail inner edge width/2 - 10.
