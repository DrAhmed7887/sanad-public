# Requirements: Sanad ward board UI

Spec-driven requirements for the offline ward board (`src/sanad/board.py` → `dist/board.html`). UI source of truth: `docs/UI_FLOW.md`, **APPROVED at Gate G2** by the clinical lead (Ahmed Zayed, physician, 8 Nov 2026, decision D27 in `docs/DECISIONS.md`, with the four G2 answers). Clinical source of truth is still `docs/EVIDENCE.md` (frozen baseline v3) and the oracle `data/SCENARIOS.md`; the board **displays** precomputed results and never re-implements or changes a rule. Every screen, label, ordering rule and simulated action below traces to a line of `docs/UI_FLOW.md`; nothing here adds a screen, wording, colour meaning safe/green, ranking or feature that `UI_FLOW.md` does not contain.

Acceptance criteria use EARS: "WHEN <trigger/condition> THE SYSTEM SHALL <response>." "The grid" = the 5-minute evaluation grid (19:00 … 07:00). "As known at t" = only records whose documented time ≤ the selected grid time. The engine entry point is `evaluate.evaluate_ward` (produces one `GridCell` per encounter per grid point); "the embedded results" = the per-grid-point `GridCell` data serialised into the HTML.

---

## 1. Generator and offline guarantees

**US-GEN.** As the builder, I want one deterministic generator that produces a single self-contained offline HTML board from the engine's results, so the demo runs with no network, no third-party code and no persistence.

- AC-GEN-1 (entry point): WHEN the generator is run as `PYTHONPATH=src python3 -m sanad.board --out dist/board.html` (amended by D28: `-I` drops `PYTHONPATH`) THE SYSTEM SHALL call `evaluate.evaluate_ward` over the night window (19:00 → 07:00) and write exactly one HTML file to the given path.
- AC-GEN-2 (stdlib only): WHEN the generator runs THE SYSTEM SHALL import only the Python standard library and `src/sanad/` modules, with no third-party runtime dependency.
- AC-GEN-3 (self-contained): WHEN the HTML is written THE SYSTEM SHALL inline all CSS and JavaScript and SHALL NOT reference any external URL, CDN, font, image or other fetched resource (trace: UI_FLOW "Rules that apply to every screen"; conductor build constraints).
- AC-GEN-4 (no network): WHEN the page loads or runs THE SYSTEM SHALL make no network call of any kind (no `fetch`, `XMLHttpRequest`, WebSocket, `src`/`href` to a remote, no `<link>`/`<script src>` to a CDN).
- AC-GEN-5 (no persistence): WHEN simulated actions occur THE SYSTEM SHALL hold them in memory only and SHALL NOT use `localStorage`, `sessionStorage`, cookies or IndexedDB; a page reload SHALL reset every simulated action (trace: D27 answer 3; conductor build constraints).
- AC-GEN-6 (display only): WHEN the JavaScript renders a bed or episode THE SYSTEM SHALL read the precomputed `GridCell` embedded for the selected grid point and SHALL NOT compute, re-implement or change any rule, threshold, state or message.
- AC-GEN-7 (determinism): WHEN the generator is run twice over the same dataset THE SYSTEM SHALL produce byte-identical HTML output (trace: `.kiro/steering/tech.md` determinism; conductor build constraints).
- AC-GEN-8 (embedded grid): WHEN the HTML is written THE SYSTEM SHALL embed, for every 5-minute grid point and every encounter, the `GridCell` fields the UI needs (per-rule state word, reason code, detail/named missing item, approved message when `met`, combined message, feed alert, display/silence text, workflow state), and the JS SHALL only step the clock across these embedded points (trace: UI_FLOW rule 2 "simulated clock … steps through the 5-minute evaluation grid").

---

## 2. No data entry anywhere

**US-NOINPUT.** As the clinical lead, I want the board to contain no way to enter patient data, so it stays inside "no patient-data entry".

- AC-NOINPUT-1 (no free text): WHEN any screen is rendered THE SYSTEM SHALL contain no `<input>` (except non-text controls required for the clock/picklists per AC-NOINPUT-2), no `<textarea>`, no file picker (`<input type="file">`), no upload control and no login/credential field (trace: UI_FLOW Screen 1 "no file picker, upload, login or data field"; conductor build constraints).
- AC-NOINPUT-2 (fixed picklists only): WHEN a simulated action needs a choice (reason, owner, deferral time) THE SYSTEM SHALL offer it only as a fixed `<select>` picklist or fixed buttons, with no free-text entry (trace: UI_FLOW Screen 5 "chosen from a fixed list (no free text)"; D27 answer 3).
- AC-NOINPUT-3 (no import/feed): WHEN the board runs THE SYSTEM SHALL read only the embedded precomputed results and SHALL offer no upload, import, patient-data entry or external feed (trace: UI_FLOW Scope line).

---

## 3. Persistent label, intended use and verification wording

**US-LABEL.** As any viewer, I want the fictional-data label and the regulatory sentences shown verbatim, so no screen can be mistaken for clinical use.

- AC-LABEL-1 (persistent label): WHEN any screen is shown THE SYSTEM SHALL display `FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE` fixed at the top, never scrolled away or hidden, and present in every capture (trace: UI_FLOW rule 1).
- AC-LABEL-2 (intended use verbatim): WHEN Screen 1 (Start) is shown THE SYSTEM SHALL display the intended-use statement verbatim from `docs/EVIDENCE.md`: "Offline software demonstration using fictional adult ICU scenarios. Illustrates configurable rules and notification workflows. Not intended to monitor people, assess SBT readiness, detect deterioration, prioritise clinical care, or support diagnosis or treatment. Do not enter patient data. No clinical performance has been established." (trace: UI_FLOW Screen 1).
- AC-LABEL-3 (verification vs validation verbatim): WHEN Screen 1 is shown THE SYSTEM SHALL display the verification-vs-validation sentence verbatim: "Synthetic scenarios and automated checks exercise the demonstration's configured logic. They do not establish clinical performance, safety or benefit." (trace: UI_FLOW Screen 1 "the verification-vs-validation sentence, verbatim").
- AC-LABEL-4 (ward line): WHEN Screen 1 is shown THE SYSTEM SHALL display "Night of 20–21 Nov 2026 · 17 beds · fictional ward" and the two role buttons *Night nurse view* and *On-call doctor view* (trace: UI_FLOW Screen 1).

---

## 4. Evaluation-state display

**US-STATE.** As a user, I want each rule result shown as exactly one state word with its reason code and the approved extra content, so states are never reduced to colour alone.

- AC-STATE-1 (state as word): WHEN a rule result is shown THE SYSTEM SHALL display exactly one state word from {`met`, `not_met`, `unknown`, `suppressed`, `not_applicable`}; colour and icons are secondary and never the only cue (trace: UI_FLOW rule 3).
- AC-STATE-2 (reason verbatim): WHEN a rule result is shown THE SYSTEM SHALL display its reason code verbatim as in `src/sanad/states.py` (e.g. `sat_not_recorded`, `weight_missing`, `haemo_unconfirmed`, `stale_data`, `output_not_charted`), with no plain-language relabelling (trace: D27 answer 2).
- AC-STATE-3 (met content): WHEN a rule is `met` and the baseline has an approved sentence THE SYSTEM SHALL show that sentence verbatim from `src/sanad/states.py` on a bordered high-contrast chip (trace: UI_FLOW rule 3 table + "Approved strings used on screen"; D27 answer 1).
- AC-STATE-4 (not_met content): WHEN a rule is `not_met` THE SYSTEM SHALL show it as plain neutral text with its reason code (trace: UI_FLOW rule 3 table).
- AC-STATE-5 (unknown content): WHEN a rule is `unknown` THE SYSTEM SHALL show a hatched chip with the reason code **and the missing item named** (trace: UI_FLOW rule 3 table).
- AC-STATE-6 (suppressed content): WHEN a rule is `suppressed` THE SYSTEM SHALL show a paused-icon chip with the hold, its owner and its review time (e.g. "deferred until 01:30") (trace: UI_FLOW rule 3 table + Screen 5).
- AC-STATE-7 (not_applicable content): WHEN a rule is `not_applicable` THE SYSTEM SHALL show the rule name struck through with the excluded pathway (e.g. `ecmo`) (trace: UI_FLOW rule 3 table).
- AC-STATE-8 (no approved sentence): WHEN a state has no approved baseline sentence (R2a `met` alone, R2b `met` alone, feed alert, routing failure) THE SYSTEM SHALL show only the rule name, the state word and the reason code, adding no new wording (trace: D27 answer 1).

---

## 5. Silence is never reassurance; no green; no ranking

**US-SILENCE.** As the clinical lead, I want a silent bed shown only as the silence sentence, never as safe/green, and no bed ordered by severity, so the top hazard (false reassurance) is controlled.

- AC-SILENCE-1 (silence text): WHEN no rule is `met` for a bed at the selected time THE SYSTEM SHALL display exactly "No configured rule triggered on the available data" (trace: UI_FLOW rule 4; Screen 2).
- AC-SILENCE-2 (no safe words): WHEN any bed is silent or non-triggering THE SYSTEM SHALL NOT use the words safe, stable or clear, and SHALL NOT render it green anywhere in the state palette (trace: UI_FLOW rule 4; `.kiro/steering/safety.md`).
- AC-SILENCE-3 (missing never blank): WHEN a required item is missing THE SYSTEM SHALL show it as `unknown` with the item named, never blank and never folded into silence (trace: UI_FLOW rule 4).
- AC-SILENCE-4 (no banned phrase): WHEN any screen is rendered THE SYSTEM SHALL contain none of the banned phrases from `docs/EVIDENCE.md` ("monitors ventilated patients", "identifies patients ready for an SBT", "detects fluid overload", "prevents missed deterioration", "makes ICUs safer", "reduces mortality") (trace: UI_FLOW rule 8; `docs/EVIDENCE.md` banned wording).
- AC-ORDER-1 (beds by number): WHEN the ward board lists beds THE SYSTEM SHALL order them by bed number, never by severity or urgency (trace: UI_FLOW rule 7; D27 answer 4 by implication of "no ranking").
- AC-ORDER-2 (doctor list by time raised): WHEN the doctor's episode list and the inbox are listed THE SYSTEM SHALL order them by time raised, never by severity or urgency (trace: UI_FLOW rule 7; Screen 4 "in time order"; Screen 5 "(by time raised)"; D27 answer 4).

---

## 6. Failures are their own state; workflow separate

**US-FAIL.** As a user, I want a stale feed or routing failure shown as its own visible alert, and the workflow state shown beside the evaluation state, so a failure is never silence and acknowledging is never mistaken for assessment.

- AC-FAIL-1 (feed alert banner): WHEN any bed is `stale_data` at the selected time THE SYSTEM SHALL show a feed alert banner above the ward grid and on that bed, never silence (trace: UI_FLOW rule 5; Screen 2 "feed alert banner sits above the grid").
- AC-FAIL-2 (routing failure item): WHEN a routing/scheduler failure occurs THE SYSTEM SHALL show it as its own inbox item, not a missing message (trace: UI_FLOW rule 5; Screen 4).
- AC-WORKFLOW-1 (workflow beside state): WHEN an episode has a workflow state (`idle → notified → acknowledged → assessed → deferred | resolved`) THE SYSTEM SHALL show it next to, never instead of, the evaluation state (trace: UI_FLOW rule 6).
- AC-WORKFLOW-2 (acknowledge is workflow-only): WHEN Acknowledge (simulated) is used on an R3 episode THE SYSTEM SHALL move the workflow to `acknowledged`, keep the evaluation state `met` and keep the due time visible until a valid check is documented in the dataset (trace: UI_FLOW Screen 3; D27 answer 3).

---

## 7. Screen 1 — Start

**US-S1.** As a first-time user, I want to read what Sanad is not and pick a role before seeing any patient-like screen.

- AC-S1-content: WHEN Screen 1 is shown THE SYSTEM SHALL show the persistent label, the intended-use statement (AC-LABEL-2), the verification sentence (AC-LABEL-3), the ward line and the two role buttons (AC-LABEL-4) and nothing that enters data (trace: UI_FLOW Screen 1).
- AC-S1-nav: WHEN a role button is pressed THE SYSTEM SHALL open the Night nurse view (Screen 2) or the On-call doctor view (Screen 5) (trace: UI_FLOW Screen 1 "picks a role").

---

## 8. Screen 2 — Ward board (night nurse)

**US-S2.** As the night nurse, I want one view of every rule state on the ward at the selected time, with unknowns and failures as visible as prompts.

- AC-S2-grid: WHEN Screen 2 is shown THE SYSTEM SHALL show a grid of 17 bed tiles (bed 13 shows the encounter currently in the bed) ordered by bed number, each tile listing R1, R2a, R2b and R3 with their state words (trace: UI_FLOW Screen 2).
- AC-S2-silence: WHEN a tile has no `met` rule THE SYSTEM SHALL show the silence text on that tile (AC-SILENCE-1) (trace: UI_FLOW Screen 2).
- AC-S2-feedbanner: WHEN any bed is `stale_data` THE SYSTEM SHALL show the feed alert banner above the grid (AC-FAIL-1) (trace: UI_FLOW Screen 2).
- AC-S2-inbox-counter: WHEN Screen 2 is shown THE SYSTEM SHALL show an inbox counter of open simulated notifications for the nurse (trace: UI_FLOW Screen 2).
- AC-S2-clock: WHEN the user steps the simulated clock THE SYSTEM SHALL re-render every tile from the embedded `GridCell` for the new grid point, showing data as known at that time (trace: UI_FLOW rule 2; Screen 2 "steps the clock").
- AC-S2-nav: WHEN the user opens a bed tile THE SYSTEM SHALL open Screen 3; WHEN the user opens the inbox THE SYSTEM SHALL open Screen 4 (trace: UI_FLOW Screen 2).

---

## 9. Screen 3 — Bed detail (night nurse)

**US-S3.** As the night nurse, I want to see exactly which item is missing or late, so acknowledging is never mistaken for doing the check.

- AC-S3-perrule: WHEN Screen 3 is shown THE SYSTEM SHALL show, for each rule, the state word, the reason code and the engine's detail text as known at t (amended by D28: per-datum event and documented times are not shown in this build) (trace: UI_FLOW Screen 3).
- AC-S3-stale-mark: WHEN a rule is `unknown` with reason `stale_data` at the selected time THE SYSTEM SHALL show that reason code and the bed's feed alert (amended by D28: no per-datum stale mark in this build) (trace: UI_FLOW Screen 3).
- AC-S3-r3: WHEN Screen 3 shows R3 THE SYSTEM SHALL show the R3 state, reason code, the engine's detail text, the workflow state and, when overdue, the R3 message (amended by D28: last valid check and due time are shown only as far as the engine's detail text carries them) (trace: UI_FLOW Screen 3).
- AC-S3-threshold-label: WHEN Screen 3 shows R2a or R2b THE SYSTEM SHALL show the threshold label "DESIGN demo values, not emergency alarm thresholds" (trace: UI_FLOW Screen 3; "Approved strings used on screen").
- AC-S3-ack: WHEN the nurse presses Acknowledge (simulated) on an R3 episode THE SYSTEM SHALL behave per AC-WORKFLOW-2 (trace: UI_FLOW Screen 3).

---

## 10. Screen 4 — Simulated inbox (both roles)

**US-S4.** As either role, I want the notifications routed to my simulated recipient, in time order, with routing failures as their own items.

- AC-S4-routing: WHEN Screen 4 is shown THE SYSTEM SHALL list notifications routed to the role's simulated recipient in time order — R3 overdue and feed alerts to the nurse; R1 prompts and R2 messages to the doctor (trace: UI_FLOW Screen 4; rule 7 "time order").
- AC-S4-item: WHEN a notification is listed THE SYSTEM SHALL show bed, encounter, rule, time raised and workflow state (trace: UI_FLOW Screen 4).
- AC-S4-fail: WHEN a routing failure occurs THE SYSTEM SHALL show it as its own item, not a missing message (AC-FAIL-2) (trace: UI_FLOW Screen 4).
- AC-S4-nav: WHEN a notification is opened THE SYSTEM SHALL open Screen 3 (nurse) or Screen 5 (doctor) (trace: UI_FLOW Screen 4).

---

## 11. Screen 5 — Review prompt (on-call doctor)

**US-S5.** As the on-call doctor, I want the open episodes by time raised, the approved R1 wording with each criterion's source, and the combined R2 message, with simulated Assessed/Deferred actions from fixed lists only.

- AC-S5-list: WHEN Screen 5 is shown THE SYSTEM SHALL show the open episode list ordered by time raised (AC-ORDER-2) (trace: UI_FLOW Screen 5).
- AC-S5-r1: WHEN an R1 episode is opened THE SYSTEM SHALL show the approved R1 wording, the R1 state, reason code and detail, and the criteria list (0, a–f, the 120-min duration) with each criterion's source line from `docs/EVIDENCE.md` (amended by D28: no per-criterion state or data in this build) (trace: UI_FLOW Screen 5).
- AC-S5-r2: WHEN a bed with R2a and R2b both `met` is opened THE SYSTEM SHALL show the combined message, the R2a and R2b states, reason codes and detail text as known at t, and both thresholds labelled "DESIGN demo values, not emergency alarm thresholds" (amended by D28: no oxygenation series or separate 72-h balance view in this build) (trace: UI_FLOW Screen 5).
- AC-S5-assess: WHEN the doctor marks Assessed (simulated) or Deferred until HH:MM (simulated), choosing reason and owner from a fixed list (no free text), THE SYSTEM SHALL show a workflow chip (`assessed`, or `deferred · owner · until HH:MM`) beside the rule's unchanged evaluation state, held in memory only; it never changes or re-evaluates the evaluation state (amended by D28 to match D27 answer 3; documented deferrals in the dataset, such as bed 15, still show `suppressed` from the precomputed results) (trace: UI_FLOW Screen 5; AC-GEN-6; AC-NOINPUT-2).

---

## 12. Fidelity to the engine (the board shows exactly what the engine computed)

**US-FIDELITY.** As the clinical lead, I want the board's displayed states to equal `evaluate.evaluate_ward` at every sample time, so the UI can never drift from the rules.

- AC-FID-1 (tiles equal engine): WHEN a tile or bed detail is shown at grid time t THE SYSTEM SHALL display the evaluation state, reason code and message that `evaluate.evaluate_ward` produced for that encounter at t (trace: UI_FLOW rule 8 + "the rules are `docs/EVIDENCE.md` … expected outcomes are `data/SCENARIOS.md`").
- AC-FID-2 (sample oracle points): WHEN rendered, the board SHALL match the engine at the oracle sample points, including: bed 1 R1 `met` at 22:20; bed 6 combined R2 message from 02:00; bed 9 feed alert 01:15–02:25; bed 10 R3 `met` 01:10–01:50 (trace: `data/SCENARIOS.md`; UI_FLOW walk-through).
- AC-FID-3 (no silence for failures): WHEN a feed outage is active THE SYSTEM SHALL show the feed alert (not silence) while the observation rules are `unknown` (`stale_data`) (trace: UI_FLOW rule 5; Screen 2).
