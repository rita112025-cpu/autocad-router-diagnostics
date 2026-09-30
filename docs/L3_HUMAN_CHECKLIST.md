# L3 - Human GUI checklist (cannot be automated)

Run in full AutoCAD 2027 on a **copy** of a drawing that contains Router output.

1. `APPLOAD` -> `autocad_router_diagnostics.lsp`. Expect one line: `Router Diagnostics 1.0.0 loaded (read-only): CTRDIAG, CTRDIAGALL, CTRDIAGEXPORT`.
   Nothing else happens, `output\` gets no new file.
2. `CTRDIAG`, click **one fitting INSERT**. Expect a command-line summary (block, insert, rotation, scale, junction, directions, one `arm` line per direction with
   expected / actual / delta / error, translation fit, candidate PATHs, issues) and three files `ctrdiag_YYYYMMDD_HHMMSS.{json,csv,txt}` in `output\`.
3. `CTRDIAG`, click something that is not a fitting (a line, a normal block): a one-line refusal, no files.
4. `CTRDIAG`, press ESC at the prompt: no error dialog, no files.
5. `bounding_box_source` in the JSON must be `"activex"` (full AutoCAD) and `bounding_box_min/max` must equal what `LIST` / selection grips show for that INSERT.
6. On a dynamic-block fitting (anonymous `*U...` name) `effective_name` must show the real block name and the fitting must be found by `CTRDIAGALL`.
7. `CTRDIAGALL` and `CTRDIAGEXPORT` complete; counts in `counts{}` match what you expect from the drawing.
8. Read-only check in the GUI: the drawing title bar shows **no asterisk** (no modification) and `U` / `UNDO` history is unchanged after the commands
   (`DBMOD` = 0 if you had just opened / saved the file).
9. Repeat 2 with the CSV opened in Excel: `Data > From Text/CSV`, encoding UTF-8; columns line up.
10. `python analyze_diagnostics.py output\<the .json>` prints the summary.
