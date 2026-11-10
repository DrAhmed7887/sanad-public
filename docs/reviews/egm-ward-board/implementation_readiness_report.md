# EGM Stage 9: Implementation Readiness

Target: `tasks.md` (lines 1-33), checked against `implementation-readiness-standard.md`. Reviewed 2026-11-08 by egm-implementation-readiness, egm-codebase-details and egm-style, each in a fresh context.

Verdict: **not ready to implement.** The plan fails the Zero-Decision Rule: the implementer would still have to design the viewer, the episodes and the simulated actions.

## What checked out (verified against code and data by codebase-details)
- The `states.*` constants exist: `R1_MET_TEXT`, `R2_COMBINED_TEXT`, `R3_OVERDUE_TEXT`, `SILENCE_TEXT`.
- `evaluate_ward` gives 145 points over the 19:00 → 07:00 window.
- The oracle times in task 4 match `SCENARIOS.md`:
  - bed 1 R1 22:20;
  - bed 6 R2a 01:05 and R2b 02:00;
  - bed 9 01:15–02:25;
  - bed 10 R3 met 01:10–01:50, not_met from 01:55, acknowledged 01:12.
- The banned-phrase list matches `EVIDENCE.md` line 88. Bed 13 carries E13A and E13B.

## Blockers
- 🔴 **IR-1. No task builds the viewer or any of Screens 1-5.**
  - Uncovered requirements include AC-S1-\*, AC-S2-grid/feedbanner/inbox-counter/clock/nav, AC-S3-\*, AC-S4-routing/nav, AC-S5-\*, and AC-STATE-1/4/5/6/7.
  - The DOM, JS, CSS and non-green palette are all undecided.
- 🔴 **IR-2 / CD-1. Task 5 says "no code change" but asserts workflow state that the code does not produce.**
  - `_episodes_from_ward` (`board.py` 224-248) freezes state at the first `met`, and `evaluate_cell` fills `workflow_states` for R3 only. So R1, R2 and feed episodes carry `""`, and bed 10 stays `notified`.
  - Bed 15 R1 gives 1 episode where 2 are needed, and R2a and R2b are separate items. The fix has to change `board.py`.
- 🔴 IR-3. The model lacks Screen 3/5 data. Missing: per-datum times, stale mark, R3 last check and due time, per-criterion R1 states, oxygenation, 72 h balance, and hold owner/time (AC-STATE-6). `criteria_sources` is missing from `build_static_copy`.
- 🔴 IR-4. Simulated actions are undefined: the picklist contents, the state-transition table and the `simActions` shape.
- 🔴 IR-5. The tests can't see markup that JS draws (bed order, controls), and the stack is stdlib only. Either render the skeletons and controls on the server with named selectors, or decide on a JS test harness (a new dependency).

## Majors
- 🟡 Routing failure has no schema: the `rule` value, the fields, and which list it belongs to.
- 🟡 **`python3 -I -m sanad.board` won't run.** There is no packaging config, and `-I` drops `src/` from the path; only `conftest.py` adds it. Also unspecified: subprocess or `main([...])`, `--data`, and whether parent folders are created.
- 🟡 For identical output bytes, fix the encoding and newlines (UTF-8 with `newline="\n"`) and define the "canonical JSON" check: parse, re-dump, compare.
- 🟡 **Bed 9 should say "R1 and R2a unknown",** not "observation rules". Name the silent beds: only bed 7 is silent all night; beds 2, 3 and 14 are `unknown` all night.
- 🟡 **Wording tests:**
  - reuse `states.BANNED_SILENCE_WORDS` (`states.py` 105);
  - match whole words in visible text only, because "safety" is in `VERIFICATION` and `r1.py` 125 accepts the input "stable";
  - define the "no green" check to cover hex, `rgb()` and `lightgreen`.
- 🟡 The offline test must allow SVG's `xmlns="http://…"` or ban inline SVG. "No `<input type=text>`" misses a bare `<input>`.
- 🟡 **Tasks don't mark files as Create/Modify.** `TRACE.md` is not in any task's file list. `dist/` is not in `.gitignore`, and committing `board.html` is undecided.
- 🟡 Listed ACs don't match the tests: AC-STATE-8 and AC-GEN-1 in task 1; AC-WORKFLOW-2 and AC-S5-assess can't be checked from Python. Line 13 says "the only controls are clock and select", which contradicts the action and role buttons.
- 🟡 The determinism claim is too strong: two in-process runs share one `PYTHONHASHSEED`. Use 2 subprocesses with different seeds.

## Nits
- Task 1 is already built (`board.py`, `test_board_model.py`, TRACE rows 25 and 27) but still unchecked.
- "static-copy block in build_board_model" should read `build_static_copy`.
- Design line 41 should say `loader.load_dataset`.
- The end of task 4 repeats task 1's equality test.
- Add a module-scoped fixture so the evaluation isn't re-run in every test.
- The `board.py` docstring cites AC-FAIL-3, which doesn't exist.
- The text uses "green" to mean passing tests (line 3), "small", and "fresh from 02:30" without saying which state.
