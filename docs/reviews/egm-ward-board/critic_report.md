# EGM Stage 7: Critic Review

Target: `design.md` (full file), checked against `feature-spec-standard.md`. Reviewed 2026-11-08 by egm-design, egm-structural and egm-style, each in a fresh context.
Context: `requirements.md`, `tasks.md`, `UI_FLOW.md`, `DECISIONS.md`, `CLAUDE.md` and `src/sanad/`.

Verdict: **fails the standard.** Two sections the standard requires are missing, and three design blockers conflict with the engine or with the G2-approved `UI_FLOW.md`.

## egm-design (architecture critic)

- 🔴 **D-1. No Alternatives Considered.** Options not weighed:
  - JS rule port;
  - recomputing in the browser;
  - local server;
  - sidecar JSON;
  - 145 pre-rendered pages;
  - episodes computed in the engine.
- 🔴 **D-2. No Risks & Limits.** Section 8 lists invariants, not failure modes or mitigations.
- 🔴 **D-3. Simulated Deferred can't work (line 95).** Precomputed cells exist only for bed 15's real hold. An arbitrary "Deferred until 03:00" has no matching cell, and the sentence contradicts itself. Choose one of three: a workflow-layer overlay, no state change, or a precomputed fixed hold grid. **Get the clinical lead's sign-off, because D27 answer 3 is in play.**
- 🔴 **D-4. Episodes and inbox don't change with the clock (lines 75, 92-93).**
  - Nothing filters out items with `time_raised > t`.
  - Workflow state is frozen at the first `met`, so bed 10 never reaches acknowledged or resolved.
  - AC-S2-inbox-counter can't be computed.
- 🔴 **D-5. Episode derivation is unspecified, and is rule logic outside the engine.**
  - Bed 15's second prompt is dropped.
  - R2a and R2b reach the doctor separately instead of as the combined message.
  - `workflow_states` covers R3 only.
- 🟡 D-6. The model can't support Screens 3 and 5. `detail` is a free string, with no per-datum times, stale flags or per-criterion states.
- 🟡 D-7. Bed 13's occupant is undefined. Add `active` per cell, or the admit and discharge times.
- 🟡 D-8. The verbatim strings (`intended_use`, `verification`, `ward_line`, `criteria_sources`) are literals typed into `board.py`, with no drift test against `EVIDENCE.md` (the D07 hazard).
- 🟡 D-9. The picklist labels are new on-screen wording that hasn't been approved (D27 answer 1).
- 🟡 D-10. The feed alert is inconsistent: `stale_data` versus `feed_alert`, and there is no per-tile alert (AC-FAIL-1). Bed 9 could show the silence sentence next to four `unknown` states, which is **D06 false reassurance**.
- 🟡 D-11. The routing-failure item has no schema. The code invents `rule: "feed_alert"`.
- 🟡 D-12. "No green" and "no safe/stable/clear" can't be enforced as written:
  - a hex or HSL green slips past a keyword check;
  - CSS `clear:` matches "clear";
  - "safety" in the mandatory sentence matches "safe".

  Use a palette allow-list and a whole-word scan of visible text only.
- 🟡 D-13. The JS viewer has no verification strategy, and `tasks.md` has no viewer task.
- 🟡 D-14. Script-block injection: JSON with `ensure_ascii=False` leaves `</script>` and U+2028 raw. Escape `<`, `>` and `&`; use `textContent`; add `<meta charset>`.
- 🟡 D-15. No size budget (about 18 encounters × 145 points × 4 rules). State that the design is limited to a fixed dataset.
- 🟢 D-16. Does `-I -m sanad.board` find `src/` from a clean checkout? There is no `--data` argument.
- 🟢 D-17. `grid_times` is not returned by `evaluate_ward`. Assert that all encounters share one grid.
- 🟢 D-18. `ACKNOWLEDGED_OPEN` is under `suppressed` in `states.py`, but UI_FLOW says R3 stays `met`. Cite the proof.
- 🟢 D-19. `string.Template` needs `$$` wherever the JS or CSS uses `$`.
- 🟢 D-20. `sort_keys` reorders the rules, so the viewer must iterate `RULE_IDS`.

## egm-structural

- 🔴 S-1. No Alternatives Considered (same as D-1).
- 🔴 S-2. No Risks & Mitigations (same as D-2).
- 🟡 S-3. No Problem / Goals / Non-Goals up front. The non-goals sit at the end, in Section 9.
- 🟡 S-4. The architecture has no parent heading. Section 0 is a provenance note that sits before it.
- 🟡 S-5. Ordering, determinism, silence and offline rules are each stated 3-4 times, with drift already showing (the `json.dumps` arguments).
- 🟡 S-6. `build_board_model` has three signatures. "Pure" is used for `main`. The import lists disagree.
- 🟡 S-7. No requirements-to-design traceability. AC-S3-perrule, AC-S3-stale-mark, AC-S3-r3, AC-S2-inbox-counter, AC-S5-r1 and AC-S5-r2 have no design coverage.
- 🟡 S-8. The design contradicts the requirements and UI_FLOW on deferral and on where episodes come from.
- 🟡 S-9. JSON escaping and `string.Template` handling are not documented.
- 🟡 S-10. There is no Testing section; "(tested)" is asserted without one.
- 🟢 S-11 to S-15. Numbering starts at 0; code fences have no language tags; bold style is inconsistent; bullets run on; D27, D06 and "conductor" are unglossed.

## egm-style

- 🟡 ST-1. The signature and "pure" claim (same as S-6).
- 🟡 ST-2. Line 52 claims `GridCell` is "exactly" what the board needs, which overclaims. Name the source of each field.
- 🟡 ST-3. Where the wording comes from contradicts itself (lines 59-68, 114, 118).
- 🟡 ST-4. "No safe/stable/clear words anywhere" is broader than AC-SILENCE-2 and can't be verified. Use the scope from line 115.
- 🟡 ST-5. Deferral: `suppressed` is an evaluation state, yet "never changes evaluation state" (same as D-3).
- 🟡 ST-6. "(tested)" and "enforced by test" present tests that don't exist yet. Write "verified by task N".
- 🟡 ST-7. "No ranking is possible" is false, because `state` and `rule` could be sorted on. Say what the code actually guarantees.
- 🟢 ST-8 to ST-13:
  - "conductor" is jargon;
  - "small" says nothing;
  - restatements repeat;
  - the banner trigger has two names;
  - "after G2" is stale, since G2 is approved;
  - "colour meaning safe/green" is awkward.
- The style reviewer couldn't check `.kiro/steering/tech.md` or `safety.md`, because they weren't supplied.
