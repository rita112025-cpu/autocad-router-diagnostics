# autocad-router-diagnostics

A **read-only AutoCAD geometry diagnostic** for the SCADA cable-tray Router output.
It lets a human or Codex get, in one command and without copying coordinates from `LIST` / `ID` / `F2`:

1. the real INSERT data of every Router fitting (Elbow / Tee / Cross),
2. the real vertices of every `SCADA-TRAY-PATH` (LINE and LWPOLYLINE, all vertices, bulges),
3. the Router XDATA on each PATH (profile / width) and every raw XDATA value,
4. the PATH junction a fitting sits on, with the arm directions (E/W/N/S) computed **from coordinates only**,
5. per arm: where the generated Straight ends (`expected`) versus where the fitting geometry really ends (`actual`),
6. a decomposition of those errors into *rigid placement offset* vs *arm length / takeoff* vs *rotation*,
7. JSON (machine) + CSV (flat) + TXT (human) files, and a Python analyser that summarises the JSON.

It **never modifies a drawing** (see [Read-only guarantee](#read-only-guarantee)). It is a separate repo and touches
none of `D:\BLOCK`, `scada-v2-block-integration`, `cable-tray-router`, `SCADA-CAD-Analyzer`.

## Files

| file | purpose |
|---|---|
| `autocad_router_diagnostics.lsp` | the tool: commands `CTRDIAG`, `CTRDIAGALL`, `CTRDIAGEXPORT` |
| `analyze_diagnostics.py` | summarises a report JSON (standard library only, no AutoCAD) |
| `output/` | reports are written here (git-ignored) |
| `tools/accore_run.py`, `tools/diagnose_real_drawing.py` | run the tool headless on a **scratch copy** of a DWG |
| `tests/` | L1 / L2 tests (see [Tests](#tests)), `tests/harness/scenes.lsp` known-answer scenes |
| `tests/whatif/elbow_origin_whatif.py` | experiment: move a fitting in a scratch copy by the reported translation and re-measure |
| `docs/L3_HUMAN_CHECKLIST.md` | what only a human in the GUI can verify |

## Install / APPLOAD

No installation, no admin rights, no ezdxf/pyautocad/.NET/ObjectARX/DLL. AutoCAD 2027 on Windows.

```
APPLOAD  ->  autocad_router_diagnostics.lsp  ->  Load
```

Loading prints one line and **does nothing else** (no scan, no file). If `SECURELOAD` blocks it, add the repo folder to
`TRUSTEDPATHS` yourself (the tool never changes settings).

Output folder defaults to `D:/github/autocad-router-diagnostics/output/`. Change it after loading with
`(setq ard:out-dir "C:/somewhere/")` (folders are created as needed; if that fails `%TEMP%` is used).

## Commands

| command | what it does |
|---|---|
| `CTRDIAG` | pick **one fitting INSERT** -> analyse it against the PATH network -> command-line summary + JSON + CSV + TXT (`ctrdiag_YYYYMMDD_HHMMSS.*`) |
| `CTRDIAGALL` | every Router fitting, PATH, Straight and junction in the drawing (`ctrdiag_..._all.*`). Lists junctions that have **no** fitting |
| `CTRDIAGEXPORT` | pure data dump, no analysis: Router INSERTs, PATHs, vertices, XDATA, generated geometry (`ctrdiag_..._export.*`) |

Fittings are recognised by **pattern**, not a fixed list: block name (after any `xref|`) matching `*SCADA_TRAY_ELBOW*`,
`*SCADA_TRAY_TEE*`, `*SCADA_TRAY_CROSS*` (`ard:fitting-patterns`); for anonymous / dynamic blocks the ActiveX `EffectiveName`;
otherwise the `CTR_GEN` XDATA tag `ELBOW|TEE|CROSS`. The profile is the text before `$` (`SCADA_V2$SCADA_TRAY_ELBOW_V2` -> `SCADA_V2`,
`SCADA_V9$...` works too; no `$` -> `DEFAULT`). Any error stops only the diagnosis (an `*error*` handler closes files); nothing needs undoing.

## What the numbers mean

* **Router XDATA schema** (confirmed by reading `cable_tray_router.lsp`, `ctr-make-path` / `ctr-get-path`): app `CTR_PATH` =
  `(1000 "PATH") (1040 width) (1000 "PROFILE=<name>")`. No XDATA -> profile `DEFAULT`, width `300`
  (reported as `profile_explicit:false`). Generated objects carry app `CTR_GEN` with `(1000 "STRAIGHT")` or the fitting type.
* **Junction / directions**: PATH segments are split at vertices, T contacts and crossings; at each node the arms are the
  segment directions. `E/W/N/S` come from the actual vector angle (tolerance 1e-4 rad, as the Router); other angles are `OTHER`.
  `classification` = `STRAIGHT | ELBOW | TEE | CROSS | UNKNOWN`, plus `END` (degree 1). `directions` are always ordered `E,W,N,S`.
  The junction chosen for a fitting is the degree>=2 node nearest to the centre of the fitting's block-definition geometry (same layout).
* **expected** (per arm) = centre of the nearest generated Straight end face on that arm.
  **actual** = centre of the farthest end face of the fitting's block-definition geometry along that arm (arcs sampled, nested blocks followed).
  `delta = actual - expected`; `axial_error_mm` > 0 means the fitting extends **past** the Straight start (overlap), < 0 a gap.
  If either side cannot be found: `"status":"NOT_COMPUTABLE"` with a `reason` - nothing is invented.
* **`translation_fit`**: solves one rigid world translation `T` from the *lateral* components of the per-arm deltas (least squares) and
  leaves a per-arm `axial_residual`. `in_block_coords` is `T` un-rotated and un-scaled. Rules of thumb:
  `T != 0`, small residuals -> placement (block origin / BASE_OFFSET); `T ~ 0`, equal axial residuals -> arm length / TAKEOFF;
  large lateral residual -> rotation mapping / wrong type / PATH direction. `hints` states these in words.
* **`junction_in_block_coords`**: where the PATH junction lies in the block's own coordinates. Identical across fittings of one block
  whatever their rotation => BASE_OFFSET is applied rotation-consistently (`analyze_diagnostics.py` checks this).
* **Thresholds are never hidden**: every report carries a `thresholds` object (`exact 0.01`, `near 1.0`, corridor `30`, end-face band `0.5`, ...).
  Connection `status`: `<=exact` EXACT, `<=near` NEAR, else MISMATCH. Path `relation`: `exact | near | unrelated` from the distance to the selected junction.
* Values named `*_mm` are drawing units; the Router assumes millimetres (`insunits` is in the header).

## JSON schema (`schema_version` "1.0")

Top level: `schema_version, tool, tool_version, mode (single|all|export), timestamp, drawing, drawing_path, acad_version, insunits, read_only,
run_note, thresholds{}, counts{}, fittings[], junctions[], paths[], generated_geometry[], warnings[]`.

`fittings[]` - always: `entity_type, handle, raw_block_name, effective_name, resolved_profile_prefix, profile, fitting_type, fitting_type_source,
insert_x/y/z, scale_x/y/z, rotation_rad, rotation_deg, extrusion, layer, layout, bounding_box_min/max, bounding_box_source
("activex" | "computed_from_block_definition"), block_definition_found, block_geometry_point_count, block_geometry_tally{}, block_bbox_local{},
block_arc_centres[], xdata_raw[]`.
Analysis (`single`/`all`): `junction{junction_x/y/z, degree, directions[], classification, profiles[], widths[], arms[]}, junction_offset_from_insert,
junction_in_block_coords, rotation_nearest_quarter_turn_deg, rotation_residual_deg, scale_is_uniform, fitting_geometry_extent_from_junction_mm{E,W,N,S},
connections[{direction, path_handle, expected[], actual[], delta_x, delta_y, error_mm, axial_error_mm, lateral_error_mm, straight_end_width_mm,
fitting_opening_width_mm, expected/actual/delta_in_block_coords, status, reason, straight_handles[]}], translation_fit{}, max_connection_error_mm,
connected_path_candidates[{handle, min_distance, nearest_point[], min_vertex_distance, junction_distance, touches_junction, profile, width, relation}],
issues[{severity FAIL|WARN, code, detail}], status OK|WARN|FAIL|NOT_COMPUTABLE`.

`paths[]`: `handle, entity_type (LINE|LWPOLYLINE), layer, layout, closed, profile, width, profile_explicit, width_explicit, has_ctr_path_xdata, has_bulge,
vertex_count, xdata_raw[{app,code,value}], vertices[{index,x,y,z[,bulge]}]` - all vertices, not just the ends.
`generated_geometry[]`: the `CTR_GEN` `STRAIGHT` polylines with vertices. `junctions[]` (`all`): every node of degree >= 2 with `fitting_handles[]`,
`issues` (`NO_FITTING_AT_JUNCTION`, `PATH_PROFILE_MISMATCH`, `PATH_WIDTH_MISMATCH`, `MULTIPLE_FITTINGS_AT_JUNCTION`, `UNSUPPORTED_TOPOLOGY`, `FITTING_FAILED`).

Issue codes on a fitting: `CONNECTION_MISMATCH` (FAIL), `CONNECTION_NEAR`, `CONNECTION_NOT_COMPUTABLE`, `OPENING_WIDTH_MISMATCH`, `FITTING_TOPOLOGY_MISMATCH` (FAIL),
`FITTING_PROFILE_MISMATCH` (FAIL), `PATH_PROFILE_MISMATCH` (FAIL), `PATH_WIDTH_MISMATCH`, `FITTING_UNPREFIXED_PATH_PROFILE`, `NO_JUNCTION`,
`BLOCK_DEFINITION_MISSING` (FAIL), `INSERT_EXTRUSION_NOT_Z`.

CSV columns (fittings, junctions, PATHs in one file): `drawing, handle, object_type, block_name, fitting_type, profile, width, x, y, z, scale_x, scale_y,
rotation_deg, junction_x, junction_y, degree, classification, max_connection_error_mm, status, layout, directions, issues`. UTF-8, RFC-4180 quoting.

## Python analyser

```
python analyze_diagnostics.py output\ctrdiag_YYYYMMDD_HHMMSS_all.json
python analyze_diagnostics.py report.json --json      # same data as JSON
python analyze_diagnostics.py report.json --strict    # exit code 1 when any FAIL
```

Prints: fitting count; ELBOW/TEE/CROSS counts; BASIC/V2 counts; PATH count; PROFILE_MISMATCH (fittings and PATH conflicts); the fitting with the largest
connection error; every FAIL/WARN; per fitting handle, block, position, rotation, scale, connected PATH and geometry error; and cross-fitting
consistency checks (junction-in-block constant? translation constant? rotation a function of directions?).

## Running it on a real drawing without opening it

```
python tools/diagnose_real_drawing.py D:\TEST\TEST.dwg --fitting 514
```

Copies the DWG to a scratch folder, runs the tool in `accoreconsole` on the copy, discards it, and prints the SHA-256 of the original before/after.
(`CTRDIAG` itself needs a GUI pick; the handle form runs the identical analysis code.)

## Read-only guarantee

* The source never calls `entmod entdel entmake entmakex command setvar regapp save qsave` or any `vla-put*/delete/move/...`; it uses
  `ssget entget entnext tblobjname trans getvar` and read-only ActiveX (`GetBoundingBox`, `EffectiveName`). It writes only external files.
  `tests/test_readonly_guard.py` tokenises the source (comments/strings removed) and fails on any forbidden or unreviewed function, on code that
  would run at load time, on more than one `open`, and on non-ASCII / backslash characters.
* `tests/test_engine_scenes.py` dumps the **entire drawing database** (every entity with XDATA, all symbol tables, `HANDSEED`) before and after
  each tool run inside the real AutoCAD engine and requires the dumps to be byte-identical.
* `tools/diagnose_real_drawing.py` never opens the original and hashes it before/after.

## Tests

```
python -m unittest discover -s tests
```

| level | what | needs |
|---|---|---|
| **L1 pure logic** | `test_analyzer.py` (Python analyser, JSON/CSV consumption), `test_readonly_guard.py` (static read-only proof), `test_lisp_pure.py` (AutoLISP functions run with literal data: JSON/CSV escaping, direction/classification, segment crossing, arcs/bulges, matrices, stamp, name patterns, face picking) | Python; `test_lisp_pure.py` also `accoreconsole.exe` (skipped without it) |
| **L2 AutoCAD engine** | `test_engine_scenes.py`: 27 known-answer scenes built with `entmake` in a disposable drawing (LINE/LWPOLYLINE vertices, rotation 0/90/180/270, scale != 1, BASIC/V2 blocks, Elbow/Tee/Cross topology, mixed BASIC/V2 PATH, PROFILE_MISMATCH, no XDATA, no PATH, several candidates, JSON/CSV escaping, deliberate rotation/takeoff/offset faults, read-only proof) | `accoreconsole.exe` (AutoCAD 2027); skipped without it |
| **L3 Human GUI** | `APPLOAD`, the `CTRDIAG` `entsel` pick, ActiveX `GetBoundingBox` / `EffectiveName` in full AutoCAD, ESC handling | a person: `docs/L3_HUMAN_CHECKLIST.md` |

## Known limitations

* Analysis is planar (XY). Non-`+Z` INSERT extrusion is flagged (`INSERT_EXTRUSION_NOT_Z`), not corrected. MINSERT arrays are not expanded.
* PATH entities other than LINE / LWPOLYLINE are ignored and reported (`UNSUPPORTED_PATH_ENTITY`); bulge segments are treated as chords and reported.
* Block geometry is taken from LINE, ARC, CIRCLE, LWPOLYLINE (incl. bulges), SPLINE/ELLIPSE (32 samples) and nested INSERTs (depth 3). HATCH, SOLID,
  TEXT, dimensions are ignored (counted in `block_geometry_tally` as `IGNORED:*`). Arc extremes are exact for quarter-turn rotations; otherwise sampled at 7.5 deg.
* `actual` uses the farthest end face along the arm. A block without a flat opening (e.g. a curved end) yields a narrow face; `OPENING_WIDTH_MISMATCH` flags it.
* Topology is O(n^2) in the number of PATH segments (fine for hundreds of segments, slow for tens of thousands).
* Anonymous dynamic-block fittings are recognised only where ActiveX is available (full AutoCAD, not `accoreconsole`), or through the `CTR_GEN` tag.
* `bounding_box_*` come from ActiveX in full AutoCAD; in `accoreconsole` they are computed from the block definition (`bounding_box_source` says which).
* CSV is UTF-8 without BOM; open it in Excel through *Data > From Text/CSV* (65001) if non-ASCII names matter.
* Paper-space objects are analysed within their own layout only; this is not covered by an L2 scene.
