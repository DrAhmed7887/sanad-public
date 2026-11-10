# EGM Stage 6: Comprehension Test

Targets: `design.md` (FeatureRange) and `tasks.md` (DetailedRange). The reviewer read only these two files, with no other context. Reviewed 2026-11-08 by egm-comprehension in a fresh context.

## What this proposes

The document proposes `src/sanad/board.py`, a generator. It runs `evaluate.evaluate_ward` over the 19:00–07:00 night and turns the per-bed, per-5-minute results into a JSON board model. It then writes one offline `dist/board.html` with inline CSS, the JSON and a small vanilla-JS viewer. The viewer only displays the embedded results and steps a clock index. It does no rule logic, takes no free text, stores nothing and makes no network calls. Six tasks build it in order:
1. the model;
2. the HTML and offline guarantees;
3. the verbatim wording;
4. the state checks against the oracle times;
5. ordering, simulated actions and failure items;
6. determinism.

## How the existing system works, per this document

`loader` reads `data/ward_seed42/` into a `Dataset`. `evaluate.evaluate_ward` returns, per encounter, a list of `GridCell`s, one for each 5-minute point. Each cell has `bed`, `encounter`, `t`, `results{rule_id→RuleResult}`, `combined_message`, `feed_alert`, `display_text` and `workflow_states`. The rules are R1, R2a, R2b and R3. The approved sentences and the silence text are constants in `states.py`.

The document never says what R1/R2/R3 are, what a "workflow state" is, or where episodes come from.

## Findings

- 🔴 **C-1. The origin of episodes and the inbox is unexplained (design 52, 74-75).** They are not `GridCell` fields, and no data-flow step produces them. "Episode", "episode id" and "time raised" are never defined. No task builds them.
- 🔴 **C-2. The signature and data flow disagree (design 28-36, 31, 45).** Line 31 has `build_board_model(dataset)` and line 45 has `build_board_model(ds, results)`. Task 1 says the function calls `evaluate_ward` itself, so it is unclear which is correct.
- 🔴 **C-3. Deferral via "picking the appropriate precomputed cell" can't be paraphrased (design 95).** `suppressed` is treated both as an evaluation state (the line 83 chips) and as a displayed workflow state.
- 🟡 C-4. The rules (R1, R2a, R2b, R3), the R1 criteria and the state and reason words are never defined, yet the tasks assert on them.
- 🟡 C-5. D27, D06, G2 and the AC ids are cited without links or their substance.
- 🟡 C-6. The "verbatim" `intended_use` and `verification` strings are not quoted or located. The `ward_line` hardcodes "17 beds" and the date without a check.
- 🟡 C-7. The `timeline` module is used but not listed. Whether the grid includes 07:00 is not stated, and the `+01:00` offset is not explained.
- 🟡 C-8. Bed 13's two-encounter structure and the rule for picking the occupant are vague.
- 🟡 C-9. The five screens and the doctor and nurse roles are never described; "Review prompt" is undefined.
- 🟡 C-10. The oracle times in tasks 4 and 5 don't cite `SCENARIOS.md`. Bed 10 "stays met after 01:12" seems to conflict with "not_met from 01:55". Whether a stale feed makes an inbox item or only a banner differs between the documents.
- 🟡 C-11. "Routing failure" is never defined, and nothing in the real pipeline produces it.
- 🟡 C-12. The task workflow assumes `TRACE.md` without explaining it. Per-task branch names and the dependencies between tasks are not given.
- 🟢 C-13. The `json.dumps` arguments differ between lines 77 and 109; `ensure_ascii` matters because the strings contain "·" and "–".
- 🟢 C-14. "Stdlib only" in Task 2 doesn't say whether the engine modules count.
- 🟢 C-15. The "non-green accent", the "hatched" pattern and the paused glyph are unspecified.
- 🟢 C-16. Sorting ISO strings is only correct if every value has the same offset; no tie-break is defined.
- 🟢 C-17. The hardcoded date and bed count are not checked against the dataset.
