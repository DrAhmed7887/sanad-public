# Product steering: Sanad

Steering for the whole build. Derived from `docs/EVIDENCE.md` (frozen baseline v3, signed by the clinical lead Ahmed Zayed, physician, 7 Nov 2026) and `CLAUDE.md`. Steering does not override the baseline; where they differ, the baseline wins and this file is corrected.

## What Sanad is

- An **offline software demonstration** of sourced night-shift review rules for ventilated adult ICU patients, running on a **fixed synthetic dataset only** (`data/ward_seed42/`, seed 42, 17 beds / 18 fictional encounters).
- An illustration of **configurable rules and notification workflows**: the SBT screen review candidate (R1), the oxygenation trend review (R2a), the fluid-accounting review (R2b), their combined message, and the task/response tracker (R3).
- A Kiroween 2026 entry (Frankenstein category). Kiro is the builder: specs, steering and hooks live under `.kiro/` and are never gitignored.
- Deterministic and auditable: every rule traces to a source or an explicit DESIGN rationale in `docs/EVIDENCE.md` and `docs/TRACE.md`.

## What Sanad is not

- **Not** a monitor, SBT-readiness assessor, deterioration detector, care prioritiser, or diagnosis/treatment aid.
- **Not** a medical device. It stays an offline synthetic demo precisely to remain outside the FDA device definition (FD&C Act 520(o)(1)(E)) and EU MDR Rule 11.
- **Not** fed by any real, live, uploaded or imported data. There is no patient-data entry, no upload/import, and no external feed. Recipients of notifications are simulated.
- **Not** clinically validated. AI review is not clinical validation; synthetic scenarios and automated checks do not establish clinical performance, safety or benefit.

## Intended-use statement (verbatim from docs/EVIDENCE.md)

Reproduce this text exactly on the start screen, README, video description and blog:

> "Offline software demonstration using fictional adult ICU scenarios. Illustrates configurable rules and notification workflows. Not intended to monitor people, assess SBT readiness, detect deterioration, prioritise clinical care, or support diagnosis or treatment. Do not enter patient data. No clinical performance has been established."

Controls that accompany the statement: fixed synthetic dataset only, no upload, import or patient-data entry, no external feeds; a persistent "FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE" label on every screen and capture; simulated recipients only.

## Verification vs validation (verbatim from docs/EVIDENCE.md)

> "Synthetic scenarios and automated checks exercise the demonstration's configured logic. They do not establish clinical performance, safety or benefit."

A test is reported as passed only after it has run against the identified build.

## Banned wording (from docs/EVIDENCE.md — never use publicly)

The following phrases are banned in all public material (README, UI, video, blog, social, submission):

- "monitors ventilated patients"
- "identifies patients ready for an SBT"
- "detects fluid overload"
- "prevents missed deterioration"
- "makes ICUs safer"
- "reduces mortality"

Also banned by implication of the shared definitions: describing a silent or non-triggering state as **safe, stable, clear or green** (see `.kiro/steering/safety.md`).

## Approved rule wording (use verbatim; do not paraphrase)

- R1: "Available data match the configured SBT screen. Clinician review required; this does not establish SBT or extubation readiness."
- R2 combined (R2a and R2b both met): "Worsening oxygenation with positive recorded fluid balance. Review the patient, oxygenation, fluid accounting and alternative causes (including hypovolaemia and third-spacing). This does not establish pulmonary oedema or indicate fluid removal."
- R3 overdue: "No completion recorded in this feed; verify whether performed."
- Silence: "No configured rule triggered on the available data."

## Hard gates (stop and ask the clinical lead; never automatic)

- Any change to a clinical rule, threshold or expected outcome (needs a new baseline version, a `docs/DECISIONS.md` entry and a new sign-off).
- Making the repo public, publishing, posting, recording or submitting anything publicly.
- Spending money or credits beyond the named budget.
- Signing in, accepting terms, or entering any credential.
- Force-pushing `main`, rewriting published history, or deleting non-merged branches, repos or data.
