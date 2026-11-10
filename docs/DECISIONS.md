# Decision log

Each finding from an AI review was checked against the source documents by the developer (Claude). Then the clinical lead (Ahmed Zayed, physician) signed the resulting rule version. **Model agreement is not clinical validation.** Full reviews are kept in the project's private research pack.

| ID | Date | Source of finding | Finding | Decision | Reason / check | Affects |
|---|---|---|---|---|---|---|
| D01 | 7 Nov | Astra (GPT-6) | R1 output omitted the SAT prerequisite | **Accepted** | Verified: MODE App. 3 "If the patient passes the SAT, then…" | R1 0 |
| D02 | 7 Nov | Astra | Effort can be ventilator autotriggering; a single-drug pressor cut-off hides other agents | **Accepted** | Design logic; MODE thresholds kept | R1 d, e |
| D03 | 7 Nov | Astra | AND of fluid + oxygen misses flash pulmonary oedema | **Accepted** | Split into R2a/R2b | R2 |
| D04 | 7 Nov | Astra | "Heart strain" is not inferable from these data | **Accepted** | No source supports it; label dropped | R2 wording |
| D05 | 7 Nov | Astra | Acknowledgement must not close an episode; 15-min universal escalation unsafe | **Accepted** | Workflow states separated | R3 |
| D06 | 7 Nov | Astra | False reassurance is the top hazard | **Accepted** | Five evaluation states; no green/safe | All |
| D07 | 7 Nov | Astra | Wording can make it a device (FDA CDS / EU MDR) | **Accepted** | Verified: FD&C 520(o)(1)(E) four criteria, guidance 6 Jan 2026 | Intended use |
| D08 | 7 Nov | Astra | Per-night alarm-burden estimates | **Rejected for public use** | Illustrative, not literature | — |
| D09 | 7 Nov | Argon (Gemini 4) | PILOT FiO2 ≤ 0.6 is not an SBT bundle | **Accepted** | Verified: PILOT protocol p.11, accommodation for the high-SpO2 arm | R1 bundle |
| D10 | 7 Nov | Argon | ABC excluded all vasopressors | **Rejected (unverified)** | From memory; ABC paper not open access; MODE thresholds attributed to MODE | — |
| D11 | 7 Nov | Argon | Missing confirmation coded inconsistently (bed 2 vs bed 3) | **Accepted** | Missing → `unknown`; recorded negative → `not_met` | Definitions |
| D12 | 7 Nov | Argon | Stale confirmations can carry through worsening shock | **Accepted** | 2-h validity, early end on vasoactive/sedation change | R1 d, e |
| D13 | 7 Nov | Argon | R1 can prompt an SBT in a tachypnoeic/acidotic patient | **Accepted** | Context gate from MODE tolerance limits (RR > 35, pH < 7.30) | R1 f |
| D14 | 7 Nov | Argon | Creeping FiO2 increases evade a "recent stable baseline" | **Accepted** | Baseline = 6-h minimum | R2a |
| D15 | 7 Nov | Argon | SpO2 branch silent when no target documented | **Accepted** | Fires on drop from 6-h median, target shown if present | R2a |
| D16 | 7 Nov | Argon | ECMO exclusion missing from R2 | **Accepted** | R2a `not_applicable`; R2b still applies | R2a |
| D17 | 7 Nov | Argon | Feed outage becomes unknown at 01:15, not 01:00 | **Accepted** | Freshness = 15 min, evaluated on the 5-min grid | Bed 9 oracle |
| D18 | 7 Nov | Argon | Bed 6 late entry breaks the 01:30 combined message | **Rejected** | Checked: the late entry was 2 days earlier; scenario then redesigned to test as-known-at on purpose | Bed 6 |
| D19 | 7 Nov | Argon | Bed 4 timing contradicts the convention | **Rejected** | Checked: "≥ 30 min" from 02:20 = 02:50 is consistent; v3 adds the SpO2 branch, which fires earlier | Bed 4 |
| D20 | 7 Nov | Terra (GPT-6.1 audit) | No single approved baseline (MAJOR) | **Accepted** | v3 signed and frozen in `docs/EVIDENCE.md` | All |
| D21 | 7 Nov | Terra | Oracle disagrees with signed rules (MAJOR) | **Accepted** | SCENARIOS rewritten against v3 | Scenarios |
| D22 | 7 Nov | Terra | 12-h history and as-known-at missing (MAJOR) | **Accepted** | Generator adds 12 h pre-shift; documented-time rule | Data |
| D23 | 7 Nov | Terra | Misuse controls only on paper (MAJOR) | **Accepted, deferred to build** | Fixed-data UI, no import, persistent label; release checklist before public | Build |
| D24 | 7 Nov | Terra | Planned tests must not be reported as passed | **Accepted** | Wording in EVIDENCE "Verification vs validation" | Public claims |
| D25 | 7 Nov | Terra | Commit metadata exposes personal email | **Accepted** | Noreply email for new commits; first commit fixed before going public | Repo |
| D26 | 7 Nov | Clinical lead | v3 signed and frozen | **Signed** | Ahmed Zayed, physician | Baseline |
| D27 | 8 Nov | Clinical lead | UI flow (`docs/UI_FLOW.md`) and its four G2 questions | **Approved (G2)** | Ahmed Zayed, physician: (1) no new wording, rule name + state + reason code where the baseline has none; (2) reason codes verbatim; (3) simulated actions confirmed as no patient-data entry; (4) doctor's list by time raised | UI |
| D28 | 8 Nov | Clinical lead | EGM design review of the ward-board spec (`docs/reviews/egm-ward-board/`): (a) simulated Acknowledge/Assessed/Deferred become a workflow-only chip, never a state change or re-evaluation; (b) Screens 3 and 5 show state, reason code and the engine's detail text, not per-datum times, stale marks, per-criterion R1 states, the oxygenation series or the 72-h balance; (c) R2a and R2b form one doctor item; (d) a feed-alert chip on every stale tile; (e) run command `PYTHONPATH=src python3 -m sanad.board` | **Approved** | Ahmed Zayed, physician, in chat 8 Nov ("Yes, apply fixes", after the defaults (a) and (b) were stated). Narrows UI_FLOW Screens 3 and 5 and AC-S5-assess; no clinical rule, threshold or oracle outcome changes | UI, requirements |
| D29 | 9 Nov | Clinical lead | G3 stress round 1 (`docs/reviews/G3_STRESS_ROUND_1.md`, C1): every R2a `met` carried "fluid balance unknown", even with complete fluid data (bed 6 at 02:00 showed it beside R2b met +2.60 L) | **Approved** | Ahmed Zayed, physician, in chat 9 Nov ("Approve C1"). The label is added only when R2a is `met` and R2b is `unknown` for the same cell, as `docs/EVIDENCE.md` ("if fluid data are missing or incomplete") and AC-R2a-fluid-independent already state. No rule, threshold or oracle outcome changes | R2a detail, UI |
| D30 | 10 Nov | Video review (director agent) | Three display bugs on the live board and in the film captures: embedded JSON text shown with literal entities (bed 15 "duration not yet &gt; 120 min"), raw markdown (`**`, backticks) in the R1 criteria labels, and criterion id, label and source run together ("0Passed", "12 hMODE") | **Approved** | Ahmed Zayed, physician, in chat 10 Nov ("Yes, fix app first"). Display only: no rule, wording, threshold or oracle outcome changes; the criteria strings stay verbatim | UI |
