# Tasks: Sanad ward board UI

Ordered implementation tasks.
- Each task is a branch `build/ward-board-task-<n>`, written from `design.md` to satisfy the listed requirement IDs.
- Each passes locally (`python3 -I data/check_data.py` and `pytest`) before it ships.
- Each updates `docs/TRACE.md` (test and code columns) in the same PR.
- Shared fixture: `tests/conftest.py` gains a module-scoped `board_model` (from `build_board_model(load_dataset())`) and `board_html` (from `render_html`), so the night is evaluated once per test module.
- Silent beds by the oracle: bed 7 all night. Beds 2, 3 and 14 are `unknown` all night and also show the silence text.

- [x] 1. Board model from the engine
  - Files: Create `src/sanad/board.py` (`build_board_model`, `build_static_copy`), Create `tests/test_board_model.py`
  - Requirements: AC-GEN-6, AC-GEN-8, AC-STATE-2, AC-STATE-3, AC-ORDER-1, AC-FID-1
  - Tests: every cell's `state`/`reason`/`message` equals the `GridCell` from `evaluate_ward`; enums serialise to their `.value` words; `grid_times` is the full 5-min grid; beds sorted by bed number; bed 13 carries both encounters.

- [x] 2. Episodes follow the clock; bed occupancy (built in task 1's review round plus the R2 merge in the D28 spec PR)
  - Files: Modify `src/sanad/board.py` (episode derivation per design §3c, `active` per cell per §3b), Modify `tests/test_board_model.py`
  - Requirements: AC-ORDER-2, AC-S4-item, AC-S5-list, AC-WORKFLOW-1, AC-S2-grid
  - Tests:
    - bed 15 has two R1 episodes, raised 20:35 and 01:30;
    - bed 1 has exactly one R1 episode, raised 22:20;
    - bed 6 has one R2 episode raised 01:05 whose cells carry the combined message from 02:00;
    - bed 10 has one R3 episode raised 01:10 with `end_idx` at 01:50, and its cell `workflow_states["R3"]` reads `acknowledged` at 01:15 and `resolved` at 01:55;
    - bed 9 has one nurse `feed_alert` item raised 01:15 ending 02:25;
    - episodes are sorted by (time raised, bed, encounter, rule, start index);
    - bed 13 A and B are never both `active` at the same index;
    - no episode is produced from a cell that is not `met` (no rule logic: groups are read from `state` only).

- [x] 3. HTML skeleton, offline and no-input guarantees
  - Files: Modify `src/sanad/board.py` (`render_html`, `main`), Modify `.gitignore` (`dist/`), Create `tests/test_board_offline.py`
  - Requirements: AC-GEN-1 (as amended by D28), AC-GEN-2, AC-GEN-3, AC-GEN-4, AC-GEN-5, AC-NOINPUT-1, AC-NOINPUT-2, AC-NOINPUT-3
  - Tests:
    - `main(["--out", tmp])` writes exactly one file, UTF-8, starting with `<!doctype html>` and declaring `<meta charset="utf-8">`;
    - no `<link`, no `<script src`, no `fetch(`, `XMLHttpRequest`, `WebSocket`, `localStorage`, `sessionStorage`, `document.cookie`, `indexedDB`, and no `http://` or `https://` anywhere (inline SVG is not used);
    - no `<textarea>`, and every `<input>` (if any) has `type="button"`;
    - every `<select>` has only fixed `<option>`s;
    - the embedded `board-data` JSON parses and contains no raw `<`, `>` or `&`;
    - `board.py` imports (parsed with `ast`) are stdlib or `sanad.*` only;
    - the HTML has the five `data-screen` containers and one `data-bed` tile per bed in bed-number order.

- [x] 4. Verbatim wording, persistent label, palette
  - Files: Modify `src/sanad/board.py` (static copy incl. `criteria_sources`, palette constants), Create `tests/test_board_wording.py`
  - Requirements: AC-LABEL-1..4, AC-STATE-3, AC-S3-threshold-label, AC-SILENCE-1, AC-SILENCE-2, AC-SILENCE-4, AC-S5-r1 (as amended by D28)
  - Tests:
    - the generated HTML contains verbatim the persistent label, `INTENDED_USE`, `VERIFICATION`, `WARD_LINE`, the four `states` texts, the threshold label and "fluid balance unknown";
    - each hand-typed string is found verbatim by reading `docs/EVIDENCE.md` or `docs/UI_FLOW.md` at test time (drift test);
    - no banned phrase listed in `docs/EVIDENCE.md` appears (case-insensitive);
    - no word in `states.BANNED_SILENCE_WORDS` appears as a whole word in visible text (HTML with `<script>` and `<style>` removed, plus every embedded `display_text`), allowing the fixed `VERIFICATION` sentence;
    - every colour in the `<style>` block is in the palette constants, and none is green (hue 75°–165° with saturation > 20%).

- [x] 5. Viewer: screens, clock, tiles, simulated actions
  - Files: Modify `src/sanad/board.py` (inline JS and CSS in `render_html`), Create `tests/test_board_viewer.py`
  - Requirements: AC-S1-content, AC-S1-nav, AC-S2-grid, AC-S2-silence, AC-S2-feedbanner, AC-S2-inbox-counter, AC-S2-clock, AC-S2-nav, AC-S3-perrule, AC-S3-r3, AC-S3-ack, AC-S4-routing, AC-S4-nav, AC-S5-list, AC-S5-r2, AC-S5-assess (all as amended by D28), AC-WORKFLOW-2, AC-FAIL-1, AC-STATE-4..7
  - Viewer contract: per design §4. The JS reads only `board-data`, steps an integer index, shows and hides `data-screen` containers, writes text with `textContent`, filters lists by `start_idx <= i`, shows the per-tile feed chip when the cell's `feed_alert` is true, and keeps simulated actions in an in-memory object that only sets a workflow chip.
  - Tests:
    - the script has no `innerHTML`;
    - it never compares against a state word literal (`"met"`, `"unknown"`, … do not appear inside the script except as CSS class names built from the value);
    - it references `start_idx` and `feed_alert`;
    - the Acknowledge, Assessed and Deferred controls exist on Screens 3 and 5 with fixed picklists;
    - the feed-chip element exists in every tile template.

- [x] 6. Tile states equal the engine at the oracle sample times
  - Files: Create `tests/test_board_states.py` (no code change)
  - Requirements: AC-FID-1, AC-FID-2, AC-FID-3, AC-STATE-1, AC-STATE-5, AC-S2-silence, AC-SILENCE-3
  - Tests: parse `board-data` from the generated HTML. Expected values are copied from `data/SCENARIOS.md`:
    - bed 1 R1 `met` at 22:20;
    - bed 6 combined message absent at 01:55 and present at 02:00;
    - bed 9 `feed_alert` true and R1 and R2a `unknown` (`stale_data`) at 01:15 and 02:25, `feed_alert` false at 02:30;
    - bed 10 R3 `met` 01:10 through 01:50, `not_met` at 01:55;
    - bed 7 carries the silence text and no `met` rule at every index.

- [x] 7. Ordering, workflow and failure items
  - Files: Create `tests/test_board_order_actions.py`
  - Requirements: AC-ORDER-1, AC-ORDER-2, AC-WORKFLOW-1, AC-FAIL-1, AC-FAIL-2, AC-S4-fail
  - Tests:
    - tiles in bed-number order;
    - episodes in time-raised order;
    - bed 10 R3 stays `met` at 01:15 while its workflow reads `acknowledged`;
    - bed 9 appears as a nurse `feed` item, never as silence alone;
    - a synthetic model with one `routing` episode, passed to `render_html`, renders that item in the inbox (no data added under `data/`).

- [x] 8. Determinism of the generated HTML
  - Files: Create `tests/test_board_determinism.py` (no code change)
  - Requirements: AC-GEN-7
  - Tests:
    - run `PYTHONPATH=src python3 -m sanad.board --out <tmp>` twice as subprocesses with different `PYTHONHASHSEED` values and assert byte-identical files;
    - assert the embedded JSON equals `json.dumps(json.loads(s), sort_keys=True, ensure_ascii=False, separators=(",", ":"))` after unescaping `<`, `>` and `&`.

- [x] 9. R2a "fluid balance unknown" only when fluid data are missing or incomplete (D29)
  - Files: `src/sanad/r2a.py` (the `met` detail lists the branches and the SpO2 target, without the label), `src/sanad/evaluate.py` (when a cell has R2a `met` and R2b `unknown`, append `"; fluid balance unknown"` to that cell's R2a detail; rules stay independent), `tests/test_r2a.py`, `tests/test_oracle_all_beds.py`, `docs/TRACE.md`
  - Requirements: AC-R2a-fluid-independent, D29
  - Tests:
    - bed 6 at 02:00 (R2b `met`) and bed 4 at 02:20 (R2b `not_met`): the R2a detail does not contain "fluid balance unknown";
    - a synthetic cell with R2a `met` and R2b `unknown` carries the label exactly once; R2a `not_met`/`unknown` never carries it;
    - PBT over the ward: the label appears in an R2a detail if and only if R2a is `met` and R2b is `unknown` in that cell; no R2a state changes.

- [x] 10. Navigation, clock on every screen, and the selected episode on Screen 5
  - Files: `src/sanad/board.py` (viewer + markup), `tests/test_board_viewer.py`
  - Requirements: AC-S2-nav, AC-S4-nav, AC-S5-list, AC-S5-r1, AC-S5-r2, AC-S2-inbox-counter, D27 answer 1, D28 (G3 round 1 F3, F4, F5, F8)
  - Tests:
    - clicking a bed tile opens Screen 3 for that bed; the inbox counter is a button reading "Inbox: N open (simulated)" that opens Screen 4; Screens 2–5 each have a "Start" button back to Screen 1;
    - the clock controls are visible and working on Screens 2–5;
    - Screen 5 renders the selected episode at the clock: an R1 item shows the approved R1 message and the criteria list; an R2 item with R2a and R2b both `met` shows the combined message; any other R2 item shows only the rule name, state word and reason code (never the R1 text or criteria);
    - with no episode selected, Screen 5 shows the list only.

- [x] 11. Display fixes: hidden means hidden, banner text, readable times and codes
  - Files: `src/sanad/board.py` (CSS + viewer), `tests/test_board_viewer.py`, `tests/test_board_offline.py`
  - Requirements: AC-FAIL-1, AC-S2-feedbanner, AC-STATE-3, D27 answer 2, D28 (G3 round 1 F1, F2, F6, F7, F9)
  - Tests:
    - the inline CSS contains `[hidden] { display: none !important; }` so no class rule can show a hidden element; the per-tile feed chip is hidden whenever the cell's `feed_alert` is false (bed 9 at 01:10 and 02:30);
    - the banner text is the static feed-alert label plus the affected bed numbers while any active cell has a feed alert (bed 9, 01:15–02:25), and is empty and hidden otherwise;
    - `met` chips show no reason code; every other chip shows its reason code verbatim and wraps instead of being cut off (`overflow-wrap: anywhere`);
    - every displayed time is `HH:MM`, with the date (`20 Nov` / `21 Nov`) only on the clock and where the day changes; no raw ISO string appears in visible text.

- [x] 12. Judge-facing display fixes: decoded text, emphasis, criteria rows (D30)
  - Files: `src/sanad/board.py` (viewer JS, `_render_criteria_sources`, CSS), `tests/test_board_viewer.py`, `tests/test_board_browser.py`, `docs/TRACE.md`
  - Requirements: AC-S5-r1, AC-FID-1, AC-GEN-8, D30
  - Tests:
    - the viewer reverses the Python escaping before `JSON.parse` (`&lt;` → `<`, `&gt;` → `>`, then `&amp;` → `&`), because text inside a `<script>` element is never entity-decoded by the HTML parser; in the executed browser, bed 15's R1 detail at 19:00 reads `criteria hold; duration not yet > 120 min`, and no visible text on any screen contains `&gt;`, `&lt;` or `&amp;`;
    - the criteria list renders each criterion's id, label and source as separate blocks: the id, then the label, then the source on its own line after a visible `Source:` label; in the executed browser no id is joined to its label (no `0Passed`) and no label is joined to its source (no `12 hMODE`);
    - `**text**` in a criterion label renders as `<strong>text</strong>` and `` `text` `` as `<code>text</code>`, applied after HTML escaping; no visible criteria text contains `**` or a backtick; the `CRITERIA_SOURCES` strings stay verbatim, so `tests/test_board_wording.py` passes unchanged;
    - no new colour (palette test), no `innerHTML`, and the embedded JSON and its determinism test (task 8) are unchanged.
