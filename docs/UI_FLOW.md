# Sanad UI flow (Gate G2 approved)

- **Status: APPROVED at Gate G2 by the clinical lead (Ahmed Zayed, physician), 8 Nov 2026, with the four answers recorded below (decision D27).** UI code may now be written against this flow; any change to it needs a new G2 approval. Nothing here changes a rule, threshold or expected outcome; the rules are `docs/EVIDENCE.md` (frozen baseline v3) and the expected outcomes are `data/SCENARIOS.md`.
- Scope: an **offline board over the fixed synthetic dataset** (`data/ward_seed42/`, night 2026-11-20 19:00 → 2026-11-21 07:00). No upload, import, patient-data entry or external feed. Every recipient is simulated.
- Two users: the **night nurse** (ward board, task tracker) and the **on-call doctor** (review prompts). One screen at a time: what they see, what they do next, why.

## Rules that apply to every screen

1. **Persistent label**, fixed at the top of every screen and inside every capture, never scrolled away or hidden: `FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE`.
2. **Simulated clock.** A time control steps through the 5-minute evaluation grid (19:00 … 07:00). Every screen shows data **as known at** the selected time; nothing documented later is shown early.
3. **Five evaluation states, always as words.** Each rule result shows exactly one state word (`met`, `not_met`, `unknown`, `suppressed`, `not_applicable`) plus its reason code. Colour and icons are secondary and never the only cue.
   | State | How it is shown | Extra content |
   |---|---|---|
   | `met` | Bordered, high-contrast chip | The rule's approved wording (below) |
   | `not_met` | Plain neutral text | Reason code |
   | `unknown` | Hatched chip | Reason code **and the missing item named** (e.g. `sat_not_recorded`, `weight_missing`) |
   | `suppressed` | Paused-icon chip | The hold, its owner and its review time ("deferred until 01:30") |
   | `not_applicable` | Struck-through rule name | The excluded pathway (e.g. `ecmo`) |
4. **Silence is never reassurance.** A bed with no `met` rule shows exactly: "No configured rule triggered on the available data". **No green anywhere** in the state palette, and never the words safe, stable or clear for a silent or non-triggering bed. Missing data are `unknown`, never blank and never folded into silence.
5. **Failures are their own state.** A stale feed (`stale_data`) or a routing/scheduler failure is a visible alert banner on the board and on the bed, never silence.
6. **Workflow state is separate.** The episode's workflow (`idle → notified → acknowledged → assessed → deferred | resolved`) is shown next to, never instead of, the evaluation state. Acknowledging changes only the workflow state.
7. **No ranking.** Beds and episodes are listed by bed number or by time raised, never by severity or urgency (the intended use excludes prioritising care).
8. **Only approved wording.** Rule messages are the verbatim strings in `docs/EVIDENCE.md` (also `src/sanad/states.py`). No paraphrase and no banned phrase anywhere.

Approved strings used on screen:
- R1 `met`: "Available data match the configured SBT screen. Clinician review required; this does not establish SBT or extubation readiness."
- R2a + R2b both `met`: "Worsening oxygenation with positive recorded fluid balance. Review the patient, oxygenation, fluid accounting and alternative causes (including hypovolaemia and third-spacing). This does not establish pulmonary oedema or indicate fluid removal."
- R3 `met` (overdue): "No completion recorded in this feed; verify whether performed."
- Silence: "No configured rule triggered on the available data"
- R2a with missing fluid data: "fluid balance unknown"
- R2a/R2b thresholds: "DESIGN demo values, not emergency alarm thresholds"

## Screen 1: Start

- **Sees:** the persistent label; the intended-use statement, verbatim from `docs/EVIDENCE.md`; the verification-vs-validation sentence, verbatim; "Night of 20–21 Nov 2026 · 17 beds · fictional ward"; two buttons: *Night nurse view* and *On-call doctor view*.
- **Does next:** picks a role. There is no file picker, upload, login or data field.
- **Why:** the user must read what Sanad is not before seeing any patient-like screen.

## Screen 2: Ward board (night nurse)

- **Sees:** a grid of 17 bed tiles (bed 13 shows the encounter currently in the bed) and the simulated clock. Each tile lists R1, R2a, R2b and R3 with their state words. A tile with no `met` rule shows the silence text. A feed alert banner sits above the grid while any bed is `stale_data`. An inbox counter shows open simulated notifications for the nurse.
- **Does next:** steps the clock, or opens a bed tile (Screen 3), or opens the inbox (Screen 4).
- **Why:** one view of every rule state on the ward at that moment, with unknowns and failures as visible as prompts.

## Screen 3: Bed detail (night nurse)

- **Sees:** for each rule, the state word, the reason code, and the data it used with event time and documented time (as known at t). Data older than 15 min are marked stale. For R3: the encounter's last valid check, the due time (last valid check + 2 h, or admission + 30 min) and, when overdue, the R3 message. For R2a/R2b: the threshold label "DESIGN demo values, not emergency alarm thresholds".
- **Does next:** on an R3 episode, presses **Acknowledge (simulated)**. The workflow moves to `acknowledged`; the evaluation state stays `met` and the due time stays visible until a valid check is documented in the dataset.
- **Why:** the nurse sees exactly which item is missing or late, and acknowledging is never mistaken for doing the check.

## Screen 4: Simulated inbox (both roles)

- **Sees:** notifications routed to the simulated recipient for that role, in time order: R3 overdue and feed alerts to the nurse; R1 prompts and R2 messages to the doctor. Each shows bed, encounter, rule, time raised and workflow state. A routing failure appears as its own item, not a missing message.
- **Does next:** opens a notification → Screen 3 (nurse) or Screen 5 (doctor).
- **Why:** demonstrates the notification workflow without any real recipient.

## Screen 5: Review prompt (on-call doctor)

- **Sees:** the open episode list (by time raised). Opening an R1 episode shows the approved R1 wording and a criteria list (0, a–f, the 120-min duration), each with its state, the data used and its source line from `docs/EVIDENCE.md`. Opening a bed with R2a and R2b both `met` shows the combined message, the oxygenation data, the 72-h net balance as known at t, and both thresholds labelled as DESIGN demo values.
- **Does next:** marks **Assessed (simulated)** or **Deferred until HH:MM (simulated)** with a reason and an owner chosen from a fixed list (no free text). The rule shows `suppressed` with the hold and review time; at that time the rule re-evaluates and may open a new episode.
- **Why:** the doctor reviews the patient; the board only shows that the configured criteria matched on available data and where each criterion comes from.

## Walk-through: the night as the board shows it (from `data/SCENARIOS.md`)

| Time | Bed | What the user sees |
|---|---|---|
| 19:00 | all | Board opens. Bed 2 R1 `unknown` (`sat_not_recorded`); bed 3 R1 `unknown` (`sat_not_recorded` until 19:30, then `haemo_unconfirmed`, both agents listed); bed 11 R1 and R2a `not_applicable` (`ecmo`), R2b `not_met`; bed 14 R1 `unknown` (`weight_missing`); bed 17 R2b `unknown` (`output_not_charted`) with the computed net shown (+4.25 L); bed 5 R2b `met`; bed 13 encounter A R2b `met` |
| 20:35 | 15 | R1 `met`, prompt 1 to the doctor |
| 20:45 | 15 | Doctor's documented deferral until 01:30 → R1 `suppressed` 20:45–01:25 (no reset at midnight) |
| 22:20 | 1 | R1 `met`, exactly one prompt |
| 23:00–23:15 | 13 | Encounter A leaves at 23:00 (no further evaluations); encounter B arrives 23:15: R1 `unknown` (no SAT), R2a and R2b `unknown` (`insufficient_history`) until 05:10; R3 is per encounter, never inherited |
| 23:05 | 12 | R1 `met` (DNR is not an exclusion) |
| 01:05 | 6 | R2a `met` (SpO2 branch), R2b `not_met` |
| 01:10 | 10 | R3 `met` (overdue) to the nurse |
| 01:12 | 10 | Acknowledged: workflow `acknowledged`, R3 still `met` |
| 01:15 | 9 | Feed alert; all observation rules `unknown` (`stale_data`) until 02:25 |
| 01:30 | 15 | Deferral ends; R1 `met` again, new episode, prompt 2 |
| 01:55 | 10 | Valid check (performed 01:50, documented 01:52) → R3 `not_met`, workflow `resolved` |
| 02:00 | 6 | Late-documented 1.0 L becomes known → R2b `met` → combined R2 message |
| 02:20 | 4 | R2a `met` (SpO2 branch); R2b `not_met` |
| 02:30 | 9 | Fresh data again; duration clocks restart |
| 03:05 | 16 | R2a `met` during tagged suctioning (tags never suppress the SpO2 branch); `not_met` from 03:10 |
| 04:00 | 17 | CRRT net entry known: computed net falls to +2.5 L; R2b stays `unknown` (`output_not_charted`) |
| 05:15 | 13 | Encounter B: R2a and R2b `not_met` |
| 06:35 | 15 | R1 `unknown` (SAT older than 12 h) |

Beds 7 and 8 stay `not_met` for R2a all night (invalid samples ignored; tagged pre-oxygenation) and show the silence text when nothing else is `met`.

## Questions for the clinical lead (G2)

1. **Wording gaps.** The baseline has no approved sentence for R2a `met` alone, R2b `met` alone, the feed alert, or a routing failure. This draft shows only the rule name, the state word and the reason code there. Approve that, or supply wording (a baseline change: new version and sign-off).
2. **Reason codes on screen.** Shown verbatim (e.g. `haemo_unconfirmed`). Plain-language labels would be new public wording; approve labels or keep the codes.
3. **Simulated actions.** Acknowledge / Assessed / Deferred are session-only, reset on reload, use fixed picklists (no free text) and never change an evaluation state. The dataset's own documented events (bed 10 acknowledgement, bed 15 deferral) replay automatically. Confirm this stays inside "no patient-data entry".
4. **Doctor's list order.** Time raised (no ranking). Confirm.

**Answers (clinical lead, 8 Nov 2026, D27):**
1. Approved as drafted: where the baseline has no approved sentence, the screen shows only the rule name, the state word and the reason code. No new wording; the baseline stays v3.
2. Keep the reason codes verbatim. No plain-language labels.
3. Confirmed: the simulated actions stay inside "no patient-data entry" as described (session-only, reset on reload, fixed picklists, never change an evaluation state; dataset events replay automatically).
4. Confirmed: the doctor's list is ordered by time raised. No ranking.

## Not in this flow

Judge-facing evidence views (rule-to-source traceability, test results against the identified build) come after G2 approval, per the playbook.
