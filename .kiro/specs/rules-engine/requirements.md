# Requirements: Sanad rules engine

Spec-driven requirements for the offline rules engine (`src/sanad/`). Clinical source of truth: `docs/EVIDENCE.md` (frozen baseline v3). Oracle: `data/SCENARIOS.md`. Criterion IDs match `docs/TRACE.md` (R1-0, R1-a, …). Acceptance criteria use EARS: "WHEN <trigger/condition> THE SYSTEM SHALL <response>." The engine never establishes clinical readiness, deterioration or diagnosis; it reports configured-rule outcomes on fictional data.

Notation: "the grid" = the 5-minute evaluation grid (…:00, :05, …). "as known at t" = only records whose documented time ≤ t, placed at their event time. "fresh" = observation ≤ 15 min old at t.

---

## 1. Shared definitions

**US-DEF.** As a reviewer, I want one consistent set of definitions applied to every rule, so results are comparable and auditable.

- AC-DEF-1 (evaluation states): WHEN the engine evaluates any rule at time t THE SYSTEM SHALL return exactly one evaluation state from {`met`, `not_met`, `unknown`, `suppressed`, `not_applicable`} with a reason code.
- AC-DEF-2 (workflow separate): WHEN a workflow transition occurs (`idle`→`notified`→`acknowledged`→`assessed`→`deferred`|`resolved`) THE SYSTEM SHALL leave the evaluation state and any open episode unchanged; acknowledging SHALL NOT close an episode.
- AC-DEF-3 (grid): WHEN producing results THE SYSTEM SHALL evaluate on the 5-minute clock grid using only data as known at that grid time.
- AC-DEF-4 (silence): WHEN no configured rule is `met` at t THE SYSTEM SHALL render "No configured rule triggered on the available data" and SHALL NOT render safe, stable, clear or green.
- AC-DEF-5 (freshness): WHEN a bed's newest observation is older than 15 min at t THE SYSTEM SHALL return `unknown` (reason `stale_data`) for every observation-based rule and SHALL raise a feed alert.
- AC-DEF-6 (durations): WHEN measuring "more than N min" / "at least N min" THE SYSTEM SHALL count from the latest start of any required condition over observations no more than 15 min apart, and WHEN a gap exceeds 15 min THE SYSTEM SHALL restart the clock.
- AC-DEF-7 (missing vs negative): WHEN a required item was never recorded THE SYSTEM SHALL return `unknown` and name the missing item; WHEN a required item is recorded and negative THE SYSTEM SHALL return `not_met`.
- AC-DEF-8 (units FiO2): WHEN FiO2 is given as a fraction (0.21–1.0) or percent (21–100) THE SYSTEM SHALL normalise both to a fraction and treat equal values identically.
- AC-DEF-9 (weight-based dose): WHEN a weight-based dose needs conversion and a weight is recorded THE SYSTEM SHALL convert using it; WHEN the weight is missing THE SYSTEM SHALL return `unknown` (reason `weight_missing`) and SHALL NOT guess a weight.
- AC-DEF-10 (unsupported unit): WHEN a value carries an unsupported unit THE SYSTEM SHALL return `unknown` with an explicit error and SHALL NOT guess a conversion.
- AC-DEF-11 (as known at t): WHEN a record's documented time is greater than t THE SYSTEM SHALL exclude it at t; WHEN it is included THE SYSTEM SHALL place it on the timeline at its event time.
- AC-DEF-12 (confirmations): WHEN a clinician confirmation (effort or haemodynamics) is recorded THE SYSTEM SHALL treat it as valid for 2 h, and SHALL end its validity early when a vasoactive agent starts, stops or changes dose, or sedation increases.

---

## 2. R1 — SBT screen review candidate

**US-R1.** As the night doctor, I want a review candidate raised only when all configured SBT-screen criteria hold long enough, so I review the right patients without false reassurance.

- AC-R1-wording: WHEN R1 is `met` THE SYSTEM SHALL present "Available data match the configured SBT screen. Clinician review required; this does not establish SBT or extubation readiness."
- **R1-0** (SAT): WHEN a passed SAT, or a documented "SAT not indicated", exists in the previous 12 h THE SYSTEM SHALL treat criterion 0 as satisfied; WHEN none is recorded THE SYSTEM SHALL return `unknown` (reason `sat_not_recorded`); WHEN the latest qualifying SAT is older than 12 h THE SYSTEM SHALL cease to satisfy criterion 0 (oracle: beds 1,12,15 satisfy; beds 2,4 `sat_not_recorded`; bed 15 unknown from 06:35).
- **R1-a** (FiO2/PEEP): WHEN FiO2 ≤ 0.5 and PEEP ≤ 8 cmH2O on fresh data THE SYSTEM SHALL treat criterion a as satisfied, using normalised FiO2 (bed 1 charts 0.40 and 40 interchangeably).
- **R1-b** (12-h comparison): WHEN both FiO2 and PEEP are ≤ their values at the observation nearest t−12 h (within 15 min) THE SYSTEM SHALL treat criterion b as satisfied; WHEN no such reference observation exists THE SYSTEM SHALL return `unknown`.
- **R1-c** (NMBA): WHEN a neuromuscular blocking agent is infusing THE SYSTEM SHALL treat criterion c as not satisfied (`not_met`); WHEN none is infusing THE SYSTEM SHALL treat it as satisfied (unit test).
- **R1-d** (effort): WHEN a valid clinician confirmation of adequate inspiratory effort exists THE SYSTEM SHALL treat criterion d as satisfied; WHEN it is missing THE SYSTEM SHALL return `unknown`; WHEN it has expired (2 h, or early end per AC-DEF-12) THE SYSTEM SHALL NOT treat it as satisfied.
- **R1-e** (haemodynamics): WHEN SBP > 90 mmHg on every fresh observation in the window, norepinephrine < 10 mcg/min, and dopamine and dobutamine < 5 mcg/kg/min, THE SYSTEM SHALL treat the threshold part of criterion e as satisfied; WHEN any other vasoactive agent (vasopressin, epinephrine, phenylephrine, milrinone) is present THE SYSTEM SHALL require a valid clinician haemodynamics confirmation, otherwise `unknown` (reason `haemo_unconfirmed`); WHEN a weight-based pressor dose lacks a weight THE SYSTEM SHALL return `unknown` (reason `weight_missing`) (oracle: bed 3 vasopressin unconfirmed → unknown, both agents displayed; bed 14 weight missing → unknown).
- **R1-f** (context gate): WHEN respiratory rate > 35/min, or pH < 7.30 where measured, THE SYSTEM SHALL return `not_met` (reason `context_review`) regardless of other criteria (unit test).
- **R1-⏱** (duration): WHEN all of criteria 0 and a–f hold continuously for more than 120 min (first grid point after 120 min, clock from the latest criterion start, 15-min gap rule) THE SYSTEM SHALL return `met` (oracle: bed 1 met 22:20 clock from 20:15; bed 12 met 23:05; bed 15 met 20:35).
- **R1-pathways**: WHEN a bed is on VV/VA ECMO, chronic ventilation or long-term tracheostomy, prone positioning, documented intentional deep sedation, unstable intracranial pressure, or comfort-only care THE SYSTEM SHALL return `not_applicable`; WHEN the only special status is DNR THE SYSTEM SHALL NOT exclude the bed (oracle: bed 11 not_applicable; bed 12 DNR met).
- **R1-episodes**: WHEN R1 is `met` for an assessment episode THE SYSTEM SHALL raise at most one prompt for that episode regardless of polling rate, duplicate records or midnight; WHEN an "assessed" or "deferred until HH:MM" (with reason and owner) is recorded THE SYSTEM SHALL return `suppressed` until that time, then re-evaluate and may start a new episode, with no reset at midnight (oracle: bed 1 one prompt; bed 15 two prompts, suppressed 20:45–01:25).

---

## 3. R2a — oxygenation trend review

**US-R2a.** As the night team, I want worsening oxygenation surfaced independently of fluid balance, so flash events are not masked — without implying an emergency alarm.

- AC-R2a-na: WHEN a bed is on ECMO or comfort-only care THE SYSTEM SHALL return `not_applicable` for R2a.
- AC-R2a-hist: WHEN fewer than 6 h of history are available on this encounter THE SYSTEM SHALL return `unknown` (reason `insufficient_history`).
- AC-R2a-settings (settings branch): WHEN FiO2 is ≥ 0.10 above its 6-hour minimum, or PEEP is ≥ 2 cmH2O above its 6-hour minimum, for at least 30 min THE SYSTEM SHALL treat the settings branch as `met`, and THE SYSTEM SHALL exclude tagged planned-change windows (pre-oxygenation, recruitment, proning) from the 6-hour minimum (oracle: bed 4 settings branch would fire 02:50; bed 8 not_met).
- AC-R2a-spo2 (SpO2 branch): WHEN good-quality SpO2 is ≥ 3 points below the median of good-quality SpO2 over the previous 6 h for at least 5 min THE SYSTEM SHALL treat the SpO2 branch as `met`, whether or not a target is documented, and THE SYSTEM SHALL show the target when present (oracle: bed 4 met 02:20; bed 6 met 01:05; bed 16 met 03:05).
- AC-R2a-quality: WHEN SpO2 samples are not good quality THE SYSTEM SHALL ignore them in the SpO2 branch (oracle: bed 7 not_met — artefact ignored).
- AC-R2a-tags-spo2: WHEN a planned-change tag is active THE SYSTEM SHALL NOT suppress the SpO2 branch (oracle: bed 16 met at 03:05 during tagged suctioning).
- AC-R2a-fluid-independent: WHEN oxygenation worsening is valid THE SYSTEM SHALL return R2a `met` for any fluid balance (negative, low, missing); WHEN fluid data are missing or incomplete THE SYSTEM SHALL still fire R2a labelled "fluid balance unknown".

---

## 4. R2b — fluid-accounting review

**US-R2b.** As the night team, I want a low-priority fluid-accounting review from the recorded ledger, without treating missing output as zero or using charting-day resets.

- AC-R2b-balance: WHEN the rolling 72-hour net balance as known at t, deduplicated by transaction ID and summed by event time, exceeds +2,000 ml THE SYSTEM SHALL return `met` (oracle: bed 5 met; bed 6 met from 02:00; beds 4,7 not_met; bed 13A met).
- AC-R2b-asknown: WHEN a transaction's documented time is greater than t THE SYSTEM SHALL exclude it until t ≥ its documented time (oracle: bed 6 not_met until 01:55, met from 02:00).
- AC-R2b-dedup-order: WHEN duplicate transaction IDs or out-of-order records are present THE SYSTEM SHALL produce the same net as without them (invariant 6).
- AC-R2b-coverage: WHEN no urine or drain output is charted in the previous 6 h and the patient is not documented anuric THE SYSTEM SHALL return `unknown` (reason `output_not_charted`) and SHALL NOT treat missing output as zero (oracle: bed 17 unknown all night, computed net still shown).
- AC-R2b-crrt: WHEN CRRT records are present THE SYSTEM SHALL count only charted CRRT net removal and SHALL ignore gross effluent and replacement volumes (oracle: bed 17 net +4.25 L → +2.5 L once 04:00 entry known).
- AC-R2b-no-dailytotals: WHEN computing balance THE SYSTEM SHALL NOT use charting-day totals that reset at 07:00.
- AC-R2b-hist: WHEN fewer than 6 h of history exist on this encounter THE SYSTEM SHALL return `unknown` (reason `insufficient_history`).
- AC-R2b-pathways: WHEN a bed is on any pathway including ECMO THE SYSTEM SHALL still apply R2b (oracle: bed 11 not_met, R2b applies).

---

## 5. R2 combined message

**US-R2c.** As the night doctor, I want one combined review when both oxygenation and fluid reviews are met, with alternative causes listed.

- AC-R2-comb: WHEN R2a is `met` and R2b is `met` at the same grid time THE SYSTEM SHALL present "Worsening oxygenation with positive recorded fluid balance. Review the patient, oxygenation, fluid accounting and alternative causes (including hypovolaemia and third-spacing). This does not establish pulmonary oedema or indicate fluid removal." (oracle: bed 6 combined from 02:00).

---

## 6. R3 — task and response tracker

**US-R3.** As the charge nurse, I want overdue ventilation checks tracked per encounter, so a missed check is visible without inheriting another encounter's history.

- AC-R3-valid: WHEN a ventilation check records all required fields (breathing-effort assessment, haemodynamics assessment, cuff pressure in cmH2O) THE SYSTEM SHALL treat it as a valid check; WHEN any field is missing THE SYSTEM SHALL treat it as not a valid check.
- AC-R3-due: WHEN the last valid check for an encounter was at time c THE SYSTEM SHALL set the next due time to c + 2 h; WHEN an encounter is newly admitted THE SYSTEM SHALL set its first check due 30 min after admission.
- AC-R3-overdue: WHEN no valid check exists by due time + 10 min grace (inclusive) THE SYSTEM SHALL return `met` (overdue) with "No completion recorded in this feed; verify whether performed." (oracle: bed 10 met 01:10–01:50).
- AC-R3-workflow: WHEN an episode is acknowledged THE SYSTEM SHALL keep it `met` and the episode open; WHEN a valid check or a documented deferral (reason, owner, expiry) is recorded THE SYSTEM SHALL end the episode (oracle: bed 10 not_met from 01:55, workflow resolved).
- AC-R3-encounter: WHEN a different encounter's check occurs in the same bed THE SYSTEM SHALL NOT satisfy or reset the current encounter's task; THE SYSTEM SHALL NOT inherit history across a bed reassignment in either direction (oracle: bed 13 A and B never met via inheritance).
- AC-R3-failure: WHEN a feed, scheduler or routing failure occurs THE SYSTEM SHALL show it as its own alert and SHALL NOT render silence.

---

## 7. Property-based invariants (PBT-1 … PBT-12)

**US-PBT.** As the clinical lead, I want the hazard-driven invariants to hold for all generated inputs, not just the 17 beds.

- PBT-1: WHEN any mandatory datum is missing, stale or in an unresolved unit THE SYSTEM SHALL never return `met` and SHALL name the missing input.
- PBT-2: WHEN equivalent values are given in supported units THE SYSTEM SHALL return an identical result; WHEN a unit is unsupported THE SYSTEM SHALL return an explicit error.
- PBT-3: WHEN an active hold, deferral or not-applicable pathway applies THE SYSTEM SHALL raise no routine prompt and SHALL show the hold and its review time.
- PBT-4: WHEN the same episode has no relevant change THE SYSTEM SHALL raise at most one prompt, whatever the polling rate, duplicate records or midnight.
- PBT-5: WHEN oxygenation worsening is valid THE SYSTEM SHALL return R2a `met` for any fluid balance (negative, low, missing).
- PBT-6: WHEN day resets, record order or duplicate transaction IDs vary THE SYSTEM SHALL return an invariant rolling balance; WHEN a late-documented record is added THE SYSTEM SHALL change only evaluations at or after its documented time.
- PBT-7: WHEN an episode is acknowledged but not assessed THE SYSTEM SHALL keep the episode open with its deadline.
- PBT-8: WHEN another encounter's task occurs in the same bed THE SYSTEM SHALL never satisfy or reset the current encounter's task.
- PBT-9: WHEN a routing or feed failure occurs THE SYSTEM SHALL show a visible failure state and SHALL never be quiet.
- PBT-10: WHEN a bed is silent THE SYSTEM SHALL never render safe, stable, clear or green.
- PBT-11: WHEN a clinician confirmation has expired THE SYSTEM SHALL never satisfy R1 d or e with it.
- PBT-12: WHEN a planned-change tag is active THE SYSTEM SHALL never suppress the SpO2 branch of R2a.
