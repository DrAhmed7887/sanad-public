# G3 stress round 1 (9 Nov 2026)

Board generated from `main` b46ef38 with `PYTHONPATH=src python3 -m sanad.board --out dist/board.html` and driven in a browser as the night nurse and the on-call doctor.

## Passed

- Engine states on screen match `data/SCENARIOS.md` at all 35 sampled points (beds 1–17: R1 onsets, R2a/R2b onsets, bed 9 stale window 01:15–02:25, bed 10 R3 01:10–01:50 then not_met, bed 11 not_applicable, bed 13 insufficient history to 05:10, bed 14 weight_missing, bed 15 met/suppressed/met/unknown, bed 16 03:05 only, bed 17 output_not_charted with net +4.25 L then +2.50 L).
- Persistent label, intended-use and verification text verbatim; no green; no free-text input.

## Defects (fix before the video)

| # | Where | Defect | Fix |
|---|---|---|---|
| F1 | Ward tiles | Feed chip never hides: `.bed-feed-chip { display: inline-block }` overrides `[hidden]`. Every tile shows an empty orange bar; bed 9 keeps "feed alert" after 02:30 | `[hidden] { display: none !important; }` in the inline CSS; test that a hidden chip has no layout box |
| F2 | Above the grid | Feed banner shows but has no text during the outage | Set the banner text (static `feed_alert_label`, beds affected) |
| F3 | Ward → bed detail / inbox | Screens 3 and 4 are unreachable: tiles are not clickable, no inbox link; `show("inbox")` is never called | Tile click → Screen 3; inbox counter as a button → Screen 4; a "Start" link on every screen |
| F4 | Screen 5 | Opening any episode shows the R1 SBT text and R1 criteria, including R2 fluid items (beds 5, 6, 13A) | Render the selected episode: R1 → R1 text + criteria; R2 with both met → combined message; R2 single → rule name + state + reason code (D27-1) |
| F5 | Screen 5 | No clock on the doctor screen | Show the clock controls on Screens 3–5 |
| F6 | Chips | A `met` chip shows reason `ok_not_met` (engine default reason) | Hide the reason code on `met` chips (display only; engine unchanged) |
| F7 | All times | Raw ISO times (`2026-11-21T01:10:00+01:00`) in the clock, R3 detail and lists | Show `HH:MM` (and the date only when it changes) |
| F8 | Ward | Inbox counter is a bare "0" | Label it "Inbox: N open (simulated)" |
| F9 | Chips | Reason codes are cut off at the tile width (`sat_no…`) | Wrap reason codes |

## Needs the clinical lead

| # | Where | Finding |
|---|---|---|
| C1 | R2a detail (engine, `r2a.py:562`) | Every R2a `met` appends "fluid balance unknown", even when fluid data are complete (bed 6 at 02:00: R2b met +2.60 L and the combined message both show). `docs/EVIDENCE.md` says the label applies only "if fluid data are missing or incomplete". Proposed fix: add the label in `evaluate.py` only when R2b is `unknown` for that cell. Changes on-screen wording for R2a, so it needs a sign-off. |

## Not yet done

- Independent review of the finished board (after the fixes).
