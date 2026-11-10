# Design: Sanad ward board UI

## Problem and goals

The night team needs to see, for a fictional 17-bed ICU night, what the signed rules (R1, R2a, R2b, R3; `docs/EVIDENCE.md` v3) showed **as known at each 5-minute point**, without any risk that the page invents a state, a reassurance or a ranking.

- **Goal:** one offline HTML file that replays the engine's precomputed results for the whole night, with the five screens of `docs/UI_FLOW.md` (Gate G2, D27; amended by D28).
- **Non-goals:** no new rule, wording, colour meaning "safe", ranking or screen beyond `docs/UI_FLOW.md`; no live data; no judge-facing evidence or test-result views (UI_FLOW "Not in this flow").

Clinical source of truth is unchanged: `docs/EVIDENCE.md` (v3) and `data/SCENARIOS.md`. The board reads the fixed dataset and writes only its output file.

## 0. Constraints

- **Python 3.12, standard library only**, plus the `src/sanad/` engine (`.kiro/steering/tech.md`).
- **No network.** No external URL, CDN, remote font or image; no `fetch`, `XMLHttpRequest` or WebSocket.
- **One self-contained HTML file** with inline CSS and inline vanilla JS.
- **No persistence.** No `localStorage`, `sessionStorage`, cookies or IndexedDB. Simulated actions live in memory and reset on reload (D27 answer 3).
- **The JS never re-implements a rule** and never computes an evaluation state (AC-GEN-6). It reads embedded values by index.
- **No data entry.** No text, file or upload input; simulated actions use fixed buttons and `<select>` picklists (AC-NOINPUT-*).
- **Verbatim wording only.** Messages come from `src/sanad/states.py`; reason codes are shown verbatim (D27 answer 2); where no approved sentence exists, show rule name + state word + reason code (D27 answer 1).
- **Ordering.** Beds by bed number; doctor episodes and inbox by time raised (D27 answer 4).
- **Determinism.** Two runs over the same dataset give byte-identical HTML.

## 1. Architecture

```text
src/sanad/board.py   generator
dist/board.html      generated artefact (git-ignored)
```

`board.py` has three layers:

```text
build_board_model(ds, results=None) -> dict   # pure: engine results + static copy -> JSON-safe board model
render_html(model) -> str                      # pure: board model -> one HTML string
main(argv) -> int                              # the only impure layer: load dataset, write --out
```

`results` defaults to `evaluate.evaluate_ward(ds)`; tests may pass a synthetic result set. `board.py` imports `evaluate`, `loader`, `model`, `states`, `r3` and `timeline` from the engine; no engine module imports `board.py`.

Run it with `PYTHONPATH=src python3 -m sanad.board --out dist/board.html`. (`-I` is not usable: it drops `PYTHONPATH`, and the repo has no package install.) Tests call `board.main([...])` directly.

## 2. Data flow

```text
loader.load_dataset()                         # typed Dataset from data/ward_seed42/
evaluate.evaluate_ward(ds)                    # {encounter -> [GridCell]} over evaluate.night_window(ds)
build_board_model(ds, results)                # serialise cells, derive episodes, add static copy
render_html(model)                            # inline CSS + escaped JSON + inline JS
dist/board.html
```

The board serialises `GridCell`s; it does not recompute any rule result (AC-GEN-6, AC-FID-1). Two things are **derived** in `build_board_model`, both by grouping or looking up engine output, never by evaluating a rule: episodes (§3c) and the `active` flag (§3b).

## 3. The board model

### (a) Static copy

Verbatim strings. `states.py` constants are imported; the other strings are literals in `board.py` that a drift test compares with their source documents (task 3).

- `persistent_label`, `intended_use`, `verification`, `ward_line` (AC-LABEL-1..4), from `docs/EVIDENCE.md` / `docs/UI_FLOW.md`.
- `silence_text`, `r1_met_text`, `r2_combined_text`, `r3_overdue_text` from `states.py` (AC-SILENCE-1, AC-STATE-3).
- `threshold_label` ("DESIGN demo values, not emergency alarm thresholds") and `fluid_unknown_label` ("fluid balance unknown").
- `criteria_sources`: the R1 criteria labels (0, a–f, the 120-min duration) and their `docs/EVIDENCE.md` source lines (AC-S5-r1 as amended by D28: labels and sources, no per-criterion state).

### (b) Per-cell results

- `grid_times`: the ordered grid ISO times, taken from the cells; every encounter must share the same grid (asserted).
- `beds`: ordered by bed number. Each bed holds its encounters keyed by encounter id (bed 13 has two).
- Each encounter has `cells`, aligned to `grid_times`. Each cell holds, per rule id (`R1`, `R2a`, `R2b`, `R3`):
  - `state` (the `EvaluationState.value` word);
  - `reason` (the `ReasonCode.value`, verbatim);
  - `detail`;
  - `message` (the approved sentence only when `met`, else "").

  It also holds the cell-level fields `combined_message`, `feed_alert`, `display_text` and `workflow_states`, straight from the `GridCell`. In addition:
  - `active`: `r3.is_active(r3.context_for(ds, encounter), t)`, the same test the engine uses for `feed_alert`. The viewer shows, for each bed, the encounter whose cell is `active` at the selected index. For bed 13 that is A while A is admitted and B once B is admitted; when neither is active the tile shows the bed as empty.

### (c) Episodes

An **episode** is a maximal run of consecutive grid points in one encounter where a rule group is `met`:

- `R1` group: R1 `met`.
- `R2` group: R2a `met` **or** R2b `met`. R2a and R2b are one doctor item. The item shows `combined_message` while it is set; otherwise rule name + state word + reason code (D27 answer 1).
- `R3` group: R3 `met`.

The model holds two lists: `episodes` (the doctor's: groups `R1` and `R2`) and `inbox` (the nurse's: group `R3` and feed alerts). Each item has:
- `bed`, `encounter`;
- `rule`: the group name, `R1`, `R2` or `R3`;
- `start_idx` and `end_idx`, the first and last `met` index;
- `time_raised` (= `grid_times[start_idx]`) and `time_ended` (the first grid time after the run, or `null` if it is still open at 07:00);
- `workflow_state`, read at `end_idx` as a summary. The viewer shows the workflow from the cell at the selected index, not this field.

The episode id is `<encounter>:<rule>:<start_idx>`.

A feed alert is an inbox item built the same way, as a run of `feed_alert` true, with `rule` `feed_alert`. A routing failure is an inbox item with `rule` `routing`. Nothing in the dataset produces one: the type exists so the viewer can show it, and it is tested with a synthetic model.

Items are sorted by `(time_raised, bed number, encounter, rule, start_idx)`. This gives bed 15 two R1 episodes (20:35 and 01:30), bed 1 one, and bed 6 one R2 episode from 01:05 that shows the combined message from 02:00.

### (d) Serialisation

- Enums are written as `.value` words; times as ISO strings with the dataset offset.
- The JSON is canonical (sorted keys, compact separators).
- It is embedded in `<script type="application/json" id="board-data">`, with `<`, `>` and `&` escaped as `<`, `>`, `&` so no data can close the tag.
- The document declares `<meta charset="utf-8">` and is written as UTF-8 with `\n` newlines.

## 4. HTML and viewer

- **Skeleton rendered by Python.** `render_html` writes:
  - the persistent label banner;
  - the feed-alert banner region;
  - one container per screen (Start, Ward board, Bed detail, Inbox, Review prompt), each with a stable `data-screen` attribute;
  - one tile per bed in bed-number order, with `data-bed`;
  - the clock buttons;
  - the action buttons and the fixed `<select>` picklists (reason, owner, deferral time).

  So the structure, controls and order can be tested from the HTML string.
- **The JS only:**
  - holds the clock index and the current screen;
  - shows and hides containers;
  - fills text with `textContent` (never `innerHTML`) from the embedded values at the selected index.
- **Tiles.** Each tile shows the active encounter's state chips. When `display_text` is set it shows the silence text. When the cell's `feed_alert` is true it also shows a **feed-alert chip on the tile**, so a stale bed never reads as silence alone (D06; AC-FAIL-1). The banner above the grid shows while any active cell has `feed_alert`.
- **Palette.** Neutral greys plus one non-green accent for `met`. The allowed colours are listed as constants in `board.py` and checked by test. Chip treatments:
  - `unknown` hatched;
  - `suppressed` with a paused glyph;
  - `not_applicable` with the rule name struck through.
- **Clock filter.** The inbox shows items raised by the selected point (`start_idx <= i`). The doctor's Screen 5 list shows only items still open at that point (`start_idx <= i <= end_idx`). An episode is "open" at `i` while `i <= end_idx`, or, for R3, while `states.is_open(workflow_states["R3"] at i)`. The inbox counter (AC-S2-inbox-counter) counts open nurse items at `i`. Workflow state is read from the cell at `i`, not frozen at `start_idx`.
- **Simulated actions (D28).** Acknowledge, Assessed and Deferred until HH:MM change only a displayed workflow chip held in a JS object keyed by episode id:
  - `acknowledged`, `assessed`, or `deferred · owner · until HH:MM`.

  They never change the evaluation state, never pick a different cell, and never re-evaluate, so the rule's own state chip keeps showing the engine's value. The dataset's own documented events (bed 10 acknowledgement at 01:12, bed 15 deferral 20:45–01:25) replay through the precomputed cells as the clock moves.
- **Screen 3 and 5 content (D28).** Per rule: state word, reason code and the engine's `detail` text, with embedded ISO timestamps displayed as readable `HH:MM`. For R3: the R3 message when `met`, and the workflow state. For R1 on Screen 5: the selected cell's state/reason/detail chip, the approved R1 text and the static `criteria_sources` list (the approved sentence appears only once). For R2: the combined message and the threshold label. Per-datum event and documented times, stale marks, per-criterion R1 states, the oxygenation series and the 72-h balance are **not shown** in this build (requirements amended by D28).

## 5. Alternatives rejected

- **Port the rules to JS:** two implementations that can drift; breaks AC-GEN-6.
- **Local HTTP server or a sidecar JSON file:** breaks one-file offline use.
- **Episodes or per-datum evidence computed in the engine:** changes `GridCell`, every rule module and its tests for a demo display need.
- **Precomputed counterfactual cells for each deferral option:** multiplies data and tests; replaced by the workflow-only overlay (D28).
- **Pre-rendered HTML per grid point:** 145 copies of the markup; the JS-fills-text approach keeps the file small and still testable.

## 6. Risks and limits

- **Fixed dataset only.** Sized for 18 encounters × 145 points × 4 rules; not designed for live data or larger wards.
- **JS behavior needs execution as well as structure checks.** `tests/test_board_browser.py` drives the generated local HTML in headless Chromium with the browser context offline, covering the simulated workflows, selected detail, open-list filtering, readable times and positive feed/R2 flows. The structural tests remain as a second guard for `textContent`, embedded-index lookup and no state-word literals. Playwright and Chromium are test-only tooling; neither is imported or fetched by the generated board.
- **Hand-typed wording can drift** from `docs/EVIDENCE.md`. This is mitigated by a test that reads the source document and compares each string.
- **Script-block injection** from data text is mitigated by the escaping in §3d.
- **False reassurance (D06)** on a stale bed is mitigated by the per-tile feed chip.
