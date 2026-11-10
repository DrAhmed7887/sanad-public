# EGM Consolidated Review: Sanad ward board spec

**Spec:** `.kiro/specs/ward-board/` (design.md, tasks.md)
**Date:** 2026-11-08
**Tool:** Google Elephant-Goldfish Model v0.1.1, run without stopping between stages, with 10 fresh-context reviewers.

**Verdict: don't build further from this spec until fixes 1–3 below are done.**
- The architecture is sound: one generator, one offline HTML file, and a viewer that only displays.
- The episode and inbox model is wrong, and the viewer itself is never specified.
- All fixes stay in `board.py` and the spec. **No engine change is needed** (Stage 8).

Stage reports in this folder: `zoom_out_report.md` (5), `comprehension_report.md` (6), `critic_report.md` (7), `intermediate_zoom_out_report.md` (8), `implementation_readiness_report.md` (9).

## Action items

### 🔴 Blockers

**1. Episodes and inbox must change with the clock.**
- **Problem:**
  - `_episodes_from_ward` takes only the first `met` per rule.
  - Bed 15's second R1 prompt (01:30) is lost.
  - Bed 10 never reaches acknowledged or resolved.
  - R2a and R2b go to the doctor separately.
  - The inbox counter can't be computed.
  - Items raised after the selected time show early.
- **Fix:**
  - An episode becomes a run of consecutive `met` cells with `start_idx` and `end_idx`.
  - R2 is merged wherever `combined_message` is set.
  - The viewer lists episodes with `start_idx <= i` and reads each one's workflow state from the cell at `i`.
  - The inbox counter uses `states.is_open`.
  - This is about 30 lines in `board.py`.
- **Source findings:** IC-B1, D-4, D-5, C-1, ZO-2, M1, IR-2, CD-1.

**2. Simulated Deferred must be decided.**
- **Problem:** "picking the precomputed cell" can't work for an arbitrary time. It also contradicts D27 answer 3.
- **Fix:** Acknowledge, Assessed and Deferred become a workflow-only overlay. Amend AC-S5-assess to match D27 answer 3. Define the picklist options.
- **Clinical lead must sign off.**
- **Source findings:** D-3, ZO-3, IC-M2, C-3, ST-5, M2, IR-4.

**3. Add viewer tasks to `tasks.md`, one per screen.** Each task names its selectors and tests. Draw the skeletons and controls on the server so that Python tests can see them.
- **Source findings:** IR-1, IR-5, IC-M4, D-13.

**4. Decide Screens 3 and 5.**
- **(a)** Cut AC-S3-perrule, AC-S3-stale-mark and AC-S5-r1 down to what `detail` carries. *(cheapest)*
- **(b)** Add a flat `evidence` list per cell, built in `board.py`.

Per-criterion R1 states would have to come from `r1`.
- **Source findings:** ZO-1, IC-M1, D-6, S-7, M3, IR-3.

**5. Add the two sections the standard requires, short versions only.** "Alternatives rejected" (about 5 bullets) and "Risks and limits" (about 4 lines).
- **Source findings:** D-1, D-2, S-1, S-2, M6.

### 🟡 Majors

**6. D06 false reassurance.** The tile needs a feed-alert chip beside the silence text, driven by `cell.feed_alert`. Without it, bed 9 at 01:15 shows "No configured rule triggered" next to four `unknown` states.
- **Source findings:** D-10, M7.

**7. Bed 13.** Give each cell an `active` flag from `r3.is_active`.
- **Source findings:** IC-M3, D-7, C-8, M4.

**8. Make the spec match the code:**
- `build_board_model(ds, results=None)`;
- `load_dataset`;
- `evaluate.night_window`;
- `main` is the only layer that does I/O;
- `criteria_sources` is missing from `build_static_copy`;
- mark task 1 as done.
- **Source findings:** ZO-4, C-2, S-6, ST-1, M5, CD nits.

**9. Running it.** `python3 -I -m sanad.board` can't find `src/` (no packaging, and `-I` drops the path). Choose one: packaging, or `main([...])`. Fix UTF-8 with `newline="\n"`. Decide whether `dist/` is ignored.
- **Source findings:** CD-8, CD-9, D-16.

**10. Script safety.**
- Escape `<`, `>` and `&` in the embedded JSON.
- Add `<meta charset="utf-8">`.
- Use `textContent`.
- Write `$$` in `string.Template` wherever JS or CSS uses `$`.
- **Source findings:** D-14, D-19, N2, S-9.

**11. Wording tests.**
- Reuse `states.BANNED_SILENCE_WORDS`.
- Match whole words, in visible text only, because of "safety" and the r1 input "stable".
- Use a palette allow-list for "no green".
- Add a drift test comparing `INTENDED_USE`, `VERIFICATION` and `WARD_LINE` with `EVIDENCE.md`.
- **Source findings:** D-8, D-12, IC-M5, ST-4, CD-6, IR M4, N3.

**12. Routing-failure item.** Define its schema. Test it with one synthetic model; it needs no producer.
- **Source findings:** D-11, C-11, CD-4, N6.

**13. Precise test wording.**
- Bed 9 means R1 and R2a.
- Name the silent beds: 7 all night; 2, 3 and 14 are `unknown`.
- Bed 10 is `met` "through 01:50".
- Run determinism as 2 subprocesses with different `PYTHONHASHSEED` values.
- **Source findings:** CD-5, C-10, ST nits, style-9 #4.

### 🟢 Nits (batch these)
- Cut code-level detail from the design: `json.dumps` arguments, `string.Template`, `simActions`.
- Fold Sections 7 and 8 into Section 0.
- Drop "conductor" and "small"; fix "after G2"; tag the code fences; number sections from 1.

## Proposals rejected as over-engineering (Stage 8)
- Episodes or `evidence` owned by the engine.
- Counterfactual deferral branches.
- Pre-rendering every grid point.
- A size-budget section and a `--data` argument.
- Moving all wording into `states.py`.

## Traceability

| Action | Stage 5 | Stage 6 | Stage 7 | Stage 8 | Stage 9 |
|---|---|---|---|---|---|
| 1 Episodes | ZO-2, IC-B1 | C-1 | D-4, D-5 | M1 | IR-2, CD-1 |
| 2 Deferral | ZO-3, IC-M2 | C-3 | D-3, ST-5, S-8 | M2 | IR-4 |
| 3 Viewer tasks | — | C-9 | D-13 | N9 | IR-1, IR-5, CD-2, CD-3 |
| 4 Screens 3/5 | ZO-1, IC-M1 | — | D-6, S-7 | M3 | IR-3 |
| 5 Alternatives/Risks | — | — | D-1, D-2, S-1, S-2 | M6 | — |
| 6 D06 tile chip | — | — | D-10 | M7 | — |
| 7 Bed 13 | ZO-4, IC-M3 | C-8 | D-7 | M4 | — |
| 8 Spec/code drift | ZO-4, IC-N3 | C-2 | S-6, ST-1 | M5 | CD-11, CD-12 |
| 9 Running it | — | C-14 | D-16 | — | CD-8, CD-9 |
| 10 Script safety | IC-N4 | — | D-14, D-19, S-9 | N2 | — |
| 11 Wording tests | ZO-9, IC-M5 | C-6 | D-8, D-12, ST-4 | N3, N7 | CD-6 |
| 12 Routing failure | — | C-11 | D-11 | N6 | CD-4 |
| 13 Test precision | — | C-10 | — | — | CD-5 |
