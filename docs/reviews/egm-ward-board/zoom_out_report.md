# EGM Stage 5: Initial Zoom Out Review

Target: `.kiro/specs/ward-board/design.md` (lines 1-123), reviewed 2026-11-08.
Context given to the reviewers: `requirements.md`, `tasks.md`, `docs/UI_FLOW.md`, `docs/DECISIONS.md`, `CLAUDE.md`, `src/sanad/`, `scripts/`.
Reviewers: egm-zoom-out and egm-inventive-catalyst, both run in fresh contexts.

## egm-zoom-out (Skeptical Architect)

No blocker. Passes on context sufficiency, root problem, reuse of the engine, and dependency direction.

- 🟡 **ZO-1. The model has no data for Screens 3 and 5 (lines 52, 70-75).** `GridCell` carries only `state`, `reason`, `detail` and `message` per rule. Screen 3 also needs:
  - each datum with its event time and documented time;
  - a stale mark;
  - the last R3 check and its due time.

  Screen 5 needs per-criterion R1 states and sources, plus oxygenation data and the 72 h balance. Requirements AC-S3-perrule, AC-S3-stale-mark, AC-S3-r3, AC-S5-r1 and AC-S5-r2 cannot be met. Decide where this data comes from: extend the engine's results, or serialise it in `board.py`. Either way, rules must not be recomputed (AC-GEN-6).
- 🟡 **ZO-2. Episodes are undefined and unsound (lines 75, 95).**
  - In `board.py`, an episode is one item per rule, taken at the first `met` cell. Bed 15's two R1 prompts (20:35 and 01:30) collapse into one.
  - Each episode's workflow state is frozen at that first time.
  - Lists are not filtered by `time_raised <= t`.
  - The engine leaves R1 out of `workflow_states`.
- 🟡 **ZO-3. Simulated deferral relies on precomputed cells that don't exist (line 95).** It is either rule logic in JS or impossible. Option: limit the simulation to workflow state plus a banner, and flag that to the clinical lead as a deviation from the G2-approved flow.
- 🟡 **ZO-4. The design has drifted from the code `board.py` already has.**
  - `loader.load` is actually `load_dataset`.
  - `build_board_model` is given two different signatures.
  - `criteria_sources` is missing from `build_static_copy`.
  - Nothing says how the viewer picks bed 13's occupant.
  - Routing of a lone R2a or R2b `met` is undefined.
- 🟡 **ZO-5. Implementation detail at the wrong level (lines 77, 81, 83, 95-96, 101, 108-109).** `json.dumps` arguments, `string.Template`, `html.escape` and `simActions` belong in code, not the design. The `json.dumps` arguments are also written two different ways.
- 🟢 ZO-6. "Three pure functions": `main` does I/O, so it is not pure.
- 🟢 ZO-7. Section 0, Section 8 and the requirements repeat the same constraints.
- 🟢 ZO-8. Section 7 (determinism) repeats what the engine already guarantees.
- 🟢 ZO-9. It should reuse `evaluate.night_window` instead of hardcoding 19:00 → 07:00, and `states.is_open` / `WorkflowState`. The wording constants in `board.py` have no drift test against `EVIDENCE.md`.

## egm-inventive-catalyst

- 🔴 **IC-B1. Episodes and inbox are static lists without time, so they break "as known at t" and the workflow lifecycle.**
  - They are not filtered by `time_raised > t`, which leaks future items and inflates the inbox counter.
  - Bed 10's R3 can't show notified → acknowledged → resolved.
  - Bed 15 loses its second prompt.
  - A lone R2a or R2b goes to the doctor, although only the combined R2 message is approved.
  - Routing-failure items have no producer.

  **Fix:** the engine owns episodes (`episode_id`, `raised_at`, a workflow-state timeline), or each cell carries `open_episode_ids`. The viewer only looks things up.
- 🟡 **IC-M1. The model cannot supply Screens 3 and 5** (same issue as ZO-1). Add a structured `evidence` field to `RuleResult`. `tasks.md` has no viewer tasks for Screens 1-5.
- 🟡 **IC-M2. Simulated Deferred/Assessed is claimed to be both display-only and interactive.** Precompute counterfactual branches with the engine for each picklist option, or limit the simulation to Acknowledge/Assessed.
- 🟡 **IC-M3. Bed 13 occupant selection is unspecified.** Emit an `occupant` array per bed, derived from `r3.is_active`.
- 🟡 **IC-M4. JS fidelity can't be tested.** The Python tests are true by construction, and nothing runs the viewer. Pre-render each grid point's markup in Python and keep the JS to toggling `hidden`.
- 🟡 **IC-M5. The single-source claim for wording is inconsistent (lines 58-63, 68, 118).** `intended_use`, `verification` and `criteria_sources` are typed into `board.py` by hand. Move them into `states.py`, or add a test that parses `EVIDENCE.md`.
- 🟢 IC-N1. Code-level detail (same as ZO-5).
- 🟢 IC-N2. Sections 7 and 8 and the AC parentheticals repeat each other.
- 🟢 IC-N3. The signatures disagree and the window is hardcoded (same as ZO-4 / ZO-9).
- 🟢 IC-N4. The JSON inside `<script>` must escape `<`, `>` and `&` so future data can't break out of the tag.
- 🟢 IC-N5. `main` is the only impure layer; say so.
