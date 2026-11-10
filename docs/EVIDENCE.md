# Sanad rules: frozen baseline v3

- **Status: v3 SIGNED and FROZEN by the clinical lead (Ahmed Zayed, physician), 7 Nov 2026.** This file is the single build baseline. Any change needs a new version, a decision-log entry (`docs/DECISIONS.md`) and a new sign-off.
- History: v1 (research, PubMed + ClinicalTrials.gov) → v2 (after GPT-6 Astra clinical review) → v3 (after Gemini 4 Argon review and a GPT-6.1 Terra quality audit).
- Every AI finding was checked against source documents before adoption. AI review is not clinical validation.

## Intended use (verbatim on the start screen, README, video description and blog)
"Offline software demonstration using fictional adult ICU scenarios. Illustrates configurable rules and notification workflows. Not intended to monitor people, assess SBT readiness, detect deterioration, prioritise clinical care, or support diagnosis or treatment. Do not enter patient data. No clinical performance has been established."

Controls: fixed synthetic dataset only, no upload, import or patient-data entry, no external feeds; a persistent "FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE" label on every screen and capture; simulated recipients only.

## Shared definitions (apply to every rule)
- **Evaluation state** (exactly one): `met` · `not_met` · `unknown` · `suppressed` · `not_applicable`, each with a reason code. Silence is shown as "No configured rule triggered on the available data", never as safe, stable, clear or green.
- **Workflow state** (separate): `idle` → `notified` → `acknowledged` → `assessed` → `deferred` | `resolved`. Acknowledging never changes the evaluation state or closes an episode.
- **Evaluation grid:** every 5 minutes on the clock (…:00, :05, …), using data available at that moment.
- **Freshness:** an observation is fresh if it is ≤ 15 min old at the evaluation time. If a bed's newest observation is older than 15 min, every observation-based rule is `unknown` (reason `stale_data`) and a feed alert is raised.
- **Durations:** "more than N min" or "at least N min" are counted from the latest start of any required condition, on observations no more than 15 min apart. A gap longer than 15 min restarts the clock.
- **Missing vs negative:** a required item never recorded → `unknown` (the missing item is named). A recorded negative → `not_met`.
- **Units:** FiO2 is accepted as a fraction (0.21–1.0) or a percent (21–100) and normalised. A weight-based dose is converted only with a recorded weight; missing weight → `unknown`. An unsupported unit → `unknown` with an error, never a guess.
- **As known at time t:** a record counts only once its documented time ≤ t; it is placed on the timeline at its event time.
- **Clinician confirmations** (breathing effort, haemodynamics) come from the 2-hourly ventilation check. Each is valid for 2 h after it is recorded, and ends early if a vasoactive agent starts, stops or changes dose, or sedation increases.

## R1: SBT screen review candidate (for the doctor)
Wording: "Available data match the configured SBT screen. Clinician review required; this does not establish SBT or extubation readiness."
| # | Criterion | Source / rationale |
|---|---|---|
| 0 | Passed spontaneous awakening trial (SAT) in the previous 12 h, or "SAT not indicated" documented in the previous 12 h | MODE protocol (NCT05563779, App. 3, Part I): "If the patient passes the SAT, then the patient should be promptly evaluated in a Spontaneous Breathing Trial (SBT) Readiness Assessment"; 12-h window: DESIGN |
| a | FiO2 ≤ 0.5 and PEEP ≤ 8 cmH2O | MODE, verbatim |
| b | FiO2 and PEEP each ≤ their value 12 h earlier (the observation nearest t−12 h, within 15 min; none → `unknown`) | MODE: "Values of both PEEP and FiO2 ≤ values from previous 12 hours" (literal point reading: DESIGN interpretation) |
| c | No neuromuscular blocking agent infusing | MODE, verbatim |
| d | Valid clinician confirmation of adequate inspiratory effort | MODE ("Patient is exhibiting adequate inspiratory efforts"); confirmation: DESIGN |
| e | SBP > 90 mmHg on every fresh observation in the window; norepinephrine < 10 mcg/min; dopamine and dobutamine < 5 mcg/kg/min; **any other vasoactive agent** (vasopressin, epinephrine, phenylephrine, milrinone) → valid clinician haemodynamics confirmation required | MODE, verbatim thresholds; the extra-agent rule: DESIGN (one drug can hide another) |
| f | Context gate: respiratory rate > 35/min or pH < 7.30 (when measured) → `not_met`, reason `context_review` | MODE SBT tolerance limits ("Total Respiratory Rate ≤ 35 / min", "pH ≥ 7.30"); use as a pre-screen gate: DESIGN |
| ⏱ | All criteria hold for **more than 120 min** | MODE: "present for more than 2 hours" |
- `not_applicable` pathways: VV/VA ECMO, chronic ventilation or long-term tracheostomy, prone positioning, intentional deep sedation (documented), unstable intracranial pressure, comfort-only care. **DNR alone is not an exclusion.**
- One prompt per assessment episode. "Assessed" or "deferred until HH:MM" (with a reason and an owner) → `suppressed` until that time. At the deferral time, the rule re-evaluates and may start a new episode. No reset at midnight.
- One threshold bundle: MODE (default), configurable only with a logged change. The PILOT protocol's FiO2 ≤ 0.6 is **not** offered: PILOT was an oxygen-target trial, and that value was a trial-specific accommodation.
- Evidence: ABC trial (Girard, Lancet 2008, PMID 18191684): in that trial's population, a paired awakening + breathing protocol gave more days breathing without assistance (14.7 vs 11.6) and lower 1-year mortality (HR 0.68). ATS/CHEST 2017 (PMID 27762595) conditionally recommends a ventilator liberation protocol for adults ventilated > 24 h. Passing an SBT does not establish extubation readiness.

## R2a: oxygenation trend review (independent of fluid balance)
- **Settings branch:** FiO2 ≥ 0.10 above its 6-hour minimum, or PEEP ≥ 2 cmH2O above its 6-hour minimum, for at least 30 min. The 6-hour minimum excludes tagged planned-change windows (pre-oxygenation, recruitment, proning procedure).
- **SpO2 branch:** good-quality SpO2 ≥ 3 points below the median of good-quality SpO2 over the previous 6 h, for at least 5 min, **whether or not a target is documented** (the target is shown when present). Planned-change tags never suppress this branch.
- Needs ≥ 6 h of history (less → `unknown`, reason `insufficient_history`).
- `not_applicable`: ECMO, comfort-only care.
- All thresholds are DESIGN demo values, **not emergency alarm thresholds**: real deterioration must never wait for Sanad.
- If fluid data are missing or incomplete, R2a still fires, labelled "fluid balance unknown".

## R2b: fluid-accounting review (low priority)
- Rolling 72-hour net balance, as known at t, deduplicated by transaction ID, summed by event time, **> +2,000 ml** → `met`. +2 L is an arbitrary, configurable DESIGN value.
- Coverage: no urine or drain output charted in the previous 6 h (unless the patient is documented anuric) → `unknown`, reason `output_not_charted`. Missing output is never treated as zero.
- CRRT: only charted CRRT **net** removal counts; gross effluent and replacement volumes are ignored.
- Charting-day totals (reset at 07:00) are never used.
- History < 6 h on this encounter → `unknown`, reason `insufficient_history`.
- Applies to every pathway, including ECMO.
- Evidence it matters: Messmer 2020 meta-analysis (PMID 33009098; 31,076 patients; observational, adjusted): "The risk of mortality increased by a factor of 1.19 (95% CI, 1.11-1.28) per liter increase in positive fluid balance". This is an association; it does not validate the +2 L trigger. FACTT (PMID 16714767): a conservative strategy gave more ventilator-free days (14.6 vs 12.1).

**When R2a and R2b are both met:** "Worsening oxygenation with positive recorded fluid balance. Review the patient, oxygenation, fluid accounting and alternative causes (including hypovolaemia and third-spacing). This does not establish pulmonary oedema or indicate fluid removal."

## R3: task and response tracker (not continuous monitoring)
- Task: ventilation check per **encounter** (never per bed), every 2 h (DESIGN, local policy). A check counts only with all required fields: breathing-effort assessment, haemodynamics assessment and cuff pressure (cmH2O).
- Due time = last valid check + 2 h. A new encounter's first check is due 30 min after admission (DESIGN).
- `met` (overdue) when no valid check by due time + 10 min grace (inclusive); message: "No completion recorded in this feed; verify whether performed."
- The workflow continues as notified → acknowledged → assessed → resolved; only a valid check or a documented deferral (reason, owner, expiry) ends the episode.
- Feed, scheduler or routing failure is shown as its own alert, never as silence.
- Evidence that alarm burden matters: alarm-fatigue review (PMID 33202907): nurses find alarms "burdensome and too frequent".

## Property-based test invariants (Kiro PBT)
1. Any mandatory datum missing, stale or in an unresolved unit → never `met`; the missing input is named.
2. Equivalent values in supported units → identical result; an unsupported conversion → explicit error.
3. Active hold, deferral or not-applicable pathway → no routine prompt; the hold and its review time are shown.
4. Same episode without relevant change → at most one prompt, whatever the polling rate, duplicate records or midnight.
5. Valid oxygenation worsening → R2a `met` whatever the fluid balance (negative, low, missing).
6. Rolling balance is invariant to day resets, record order and duplicate transaction IDs; adding a late-documented record changes only evaluations at or after its documented time.
7. Acknowledged but not assessed → the episode stays open with its deadline.
8. Another encounter's task in the same bed never satisfies or resets the current encounter's task.
9. Routing or feed failure → a visible failure state, never quiet.
10. Silence never renders as safe, stable or green.
11. An expired confirmation never satisfies R1 d or e.
12. Tagged planned changes never suppress the SpO2 branch of R2a.

## Verification vs validation (wording for all public material)
"Synthetic scenarios and automated checks exercise the demonstration's configured logic. They do not establish clinical performance, safety or benefit." A test is reported as passed only after it has run against the identified build.

## Regulatory framing (checked 7 Nov 2026)
- FDA: software is excluded from the device definition only if it meets all four criteria of FD&C Act section 520(o)(1)(E). Criterion 1 excludes software that analyses "a pattern or signal from a signal acquisition system". Revised CDS guidance: 6 Jan 2026.
- EU MDR: software with a medical purpose can be a device even when a clinician decides (Rule 11).
- Sanad therefore stays an offline synthetic demo.
- **Banned wording:** "monitors ventilated patients", "identifies patients ready for an SBT", "detects fluid overload", "prevents missed deterioration", "makes ICUs safer", "reduces mortality".

## Public story (general; exact wording)
| Claim | Correct wording | Source |
|---|---|---|
| Nurse workload | Higher nurse workload was associated with higher adjusted odds of 30-day inpatient death (OR 1.068 per extra patient), in general hospital wards in 9 European countries | Aiken, Lancet 2014, PMID 24581683 |
| Regional ICU shortage | "Shortage of intensive care specialist physicians and nurses were in majority of countries" (scoping review, limited data) | Jalal, PLoS One 2023, PMID 37327195 |
| Night-shift stress | "Nearly 60% of participants reported moderate to high levels of stress" (one cross-sectional study) | Reshia, PLoS One 2025, PMID 41212863 |
| Patient-to-nurse ratio | A higher ratio was associated with a lower rate of ICU discharge (HR 0.96), i.e. longer stays | PMID 35672212 |
| Awakening + breathing protocol | One randomised trial found more ventilator-free days and lower one-year mortality; its NNT (7.4) applies to that trial only, never to Sanad | ABC, PMID 18191684 |

## Not verified (never used publicly)
- The original ABC (Girard 2008) screen text: not open access in PMC, so we use MODE's operationalisation.
- Reviewer claims made from memory (e.g. that ABC excluded all vasopressors).
- ERS 2007 full text (abstract only).
- Reviewer alarm-burden estimates.

## Sources
PMIDs 18191684, 27762595, 27762608, 27818329, 17470624, 16714767, 33009098, 32377766, 24717458, 24581683, 37327195, 41212863, 35672212, 33202907, 9279224; PMC11622525; protocols NCT05563779 (MODE, version 21 Jul 2023) and NCT03537937 (PILOT, version 1 May 2018); FDA CDS guidance (Jan 2026) summaries.
