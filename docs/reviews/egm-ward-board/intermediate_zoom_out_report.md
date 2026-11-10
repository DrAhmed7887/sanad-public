# EGM Stage 8: Intermediate Zoom Out

Target: `design.md`, plus the Stage 5-7 reports. Reviewed 2026-11-08 by egm-zoom-out in a fresh context. Its job here was to check whether the proposed fixes over-engineer the design.

**Verdict: no blocker, but the design can't be built as written.** Keep the architecture: one generator, one HTML file, a viewer that only displays. Three of the four spec gaps can be fixed cheaply inside `board.py`, with **no engine change**.

## Findings

- 🟡 **M1. Episodes and inbox don't change with the clock (the one real design defect).**
  - **Fix:** in `board.py`, an episode becomes a run of consecutive `met` cells per (encounter, rule), with `start_idx` and `end_idx`. R2a and R2b merge into one R2 episode wherever `combined_message` is set.
  - **Viewer:** it shows episodes with `start_idx <= i` and takes each one's workflow state from the cell at `i`. The inbox counter uses `states.is_open`.
  - **Size:** about 30 lines.
  - **Rejected:** episodes owned by the engine.
- 🟡 **M2. Simulated Deferred contradicts itself.**
  - **Fix:** Acknowledge, Assessed and Deferred become a workflow overlay only: a chip beside an evaluation state that doesn't change. Amend AC-S5-assess to match D27 answer 3. Bed 15's real deferral still replays through real `suppressed` cells.
  - **Rejected:** precomputed counterfactual branches.
  - **Needs the clinical lead's sign-off.**
- 🟡 **M3. Screens 3 and 5 have no data source. A decision is needed:**
  - (a) cut AC-S3-perrule, AC-S3-stale-mark and AC-S5-r1 down to what `detail` already carries; or
  - (b) add a flat `evidence` list per cell, built in `board.py` from `Dataset` and the `freshness` helpers.

  Per-criterion R1 states would have to come from `r1`, because building them in `board.py` would copy rule logic.
- 🟡 **M4. Bed 13's occupant:** give each cell an `active` boolean from `r3.is_active`.
- 🟡 **M5. Drift from the code:**
  - use `build_board_model(ds, results=None)` and `load_dataset`;
  - use `evaluate.night_window`;
  - say `main` is the only layer that does I/O.
- 🟡 **M6. Missing sections, minimal version only:**
  - "Alternatives rejected", about 5 bullets: JS rule port, local server, episodes in the engine, counterfactual cells, pre-rendered pages.
  - "Risks and limits", about 4 lines: fixed dataset only, no JS tests, a drift test for wording, a synthetic routing failure.
- 🟡 **M7. Hazard D06:** show a feed-alert chip on each tile, beside the silence text. `cell.feed_alert` already exists.
- 🟢 N1. Cut the code-level detail and the repeated Sections 7 and 8.
- 🟢 N2. Escape `<`, `>` and `&` in the embedded JSON, and add `<meta charset="utf-8">`.
- 🟢 N3. Add one drift test comparing `INTENDED_USE`, `VERIFICATION` and `WARD_LINE` with `EVIDENCE.md` and `UI_FLOW.md`.
- 🟢 N4. The viewer must iterate `RULE_IDS`.
- 🟢 N5. Say "stdlib only" and drop the import list.
- 🟢 N6. Routing failure: no producer; test it with one synthetic model.
- 🟢 N7. Whole-word scan of visible text only. The palette allow-list is optional.
- 🟢 N8. Line 101: replace with "the model carries no severity field".
- 🟢 N9. Drop "conductor", fix "after G2", and add viewer tasks.

## Proposals from earlier stages it would NOT adopt
- Pre-rendering markup for each grid point.
- Episodes or `evidence` fields inside the engine.
- A size-budget section and a `--data` argument.
- Moving all wording constants into `states.py`: a drift test is cheaper.

## Smallest set of changes to make it buildable
1. Episodes as `met` runs with `start_idx` / `end_idx`, filtered by the clock, with the inbox counter from `is_open`, and R2 merged (M1).
2. Simulated actions as a workflow overlay only; amend AC-S5-assess and flag it to the clinical lead (M2).
3. Decide Screens 3 and 5: cut, or the `evidence` list (M3).
4. An `active` flag per cell, and a feed-alert chip on each tile (M4, M7).
5. Fix the signatures and use `night_window`; `main` is the only layer that does I/O (M5).
6. Short Alternatives and Risks blocks (M6).
7. Cut the code-level detail; escape the JSON; add the wording drift test (N1-N3).
8. Add viewer tasks to `tasks.md`; rewrite tasks 1 and 5 to test the episode runs and the inbox filtered by the clock.
