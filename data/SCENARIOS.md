# Synthetic night ward: scenarios and expected outcomes (v3)

Written **before** the generator for v3 ran (playbook Phase 1). Rules: frozen baseline v3 (`docs/EVIDENCE.md`), signed 7 Nov 2026. One fictional adult ICU, 17 ventilated beds.
- Observations every 5 min from 2026-11-20 07:00 to 2026-11-21 07:00 (+01:00): 12 h of pre-shift history, then the night shift shown on the board (19:00–07:00).
- Ventilation checks every 2 h at odd hours, documented 4 min after they are performed. Each check carries an effort assessment, a haemodynamics assessment and a cuff pressure.
- SpO2 is noise-free; SBP, HR and RR carry small seeded noise. All patients are fictional.

Conventions (from v3 shared definitions):
- Evaluation on the 5-min grid, using data as known at that moment.
- "More than 120 min" is met at the first grid point after 120 min. "At least 30/5 min" is met at onset + 30/5 min.
- Stale data (> 15 min) → `unknown`. A never-recorded item → `unknown`; a recorded negative → `not_met`.
- History of v1/v2 expectations: see `docs/DECISIONS.md` (D17–D22).

| Bed | Scenario | Expected outcome |
|---|---|---|
| 1 | Improving; FiO2 0.50/PEEP 8 all day, 0.40/5 from 19:00 (FiO2 charted as **40** on alternate rows); SAT passed **20:15**; checks confirm effort and haemodynamics; no vasoactives | **R1 met from 22:20** (clock from 20:15); exactly **one** prompt |
| 2 | FiO2 0.40/PEEP 5; propofol 50 mcg/kg/min, RASS −4; **no SAT recorded** | **R1 unknown** all night (`sat_not_recorded`) |
| 3 | Numbers pass; SAT passed 19:30; norepinephrine 8 mcg/min **+ vasopressin 0.03 U/min**; checks record haemodynamics as "MD review requested" | **R1 unknown** all night (before 19:30 `sat_not_recorded`, then `haemo_unconfirmed`); both agents displayed |
| 4 | No SAT. At 02:10 FiO2 0.35 → 0.80 and PEEP 5 → 12 over 30 min; SpO2 96 → 86 | **R2a met from 02:20** (SpO2 −3 from 02:15, sustained 5 min; the settings branch would fire at 02:50); **R2b not_met** (+0.3 L); R1 unknown |
| 5 | +3.2 L in 72 h (known since 20 Nov 08:00); two duplicate transaction IDs; oxygenation stable | **R2b met** all night; **R2a not_met** |
| 6 | Baseline 0.40/8, SpO2 96; from 01:00 FiO2 0.55, PEEP 10, SpO2 93. Fluids: +1.6 L known, plus **1.0 L given 20:00 but documented 02:00**; one duplicate ID | **R2a met from 01:05** (SpO2 branch); **R2b not_met until 01:55, met from 02:00** (as known at t); **combined message from 02:00** |
| 7 | Poor-quality SpO2 74% at 03:00 and 03:01:30; settings unchanged; +0.8 L | **R2a not_met** (invalid samples ignored) |
| 8 | Tagged pre-oxygenation 04:00–04:05 (FiO2 1.0); SpO2 unchanged | **R2a not_met** |
| 9 | **Feed outage**: no observations 01:00–02:25 (last at 00:55, next at 02:30) | **All observation rules unknown 01:15–02:25** (`stale_data`); **feed alert from 01:15**; fresh again from 02:30 (duration clocks restart) |
| 10 | Checks to 23:00; **01:00 check missing**; acknowledgement at 01:12; valid check performed 01:50, documented 01:52 | **R3 met (overdue) 01:10–01:50**; acknowledgement leaves it met; **not_met from 01:55** (workflow `resolved`) |
| 11 | VV-ECMO; +1.0 L | **R1 not_applicable**, **R2a not_applicable**, **R2b not_met** (applies to ECMO) |
| 12 | **DNR** (not comfort care); SAT passed 21:00; otherwise like bed 1 at 0.40/5 all day | **R1 met from 23:05** (DNR is not an exclusion) |
| 13 | **Bed reassignment.** Encounter A (+2.4 L) leaves at 23:00 after a check at 22:50. Encounter B arrives 23:15 with no history; checks at 23:40 and 01:35; fluids +0.3 L | A: **R2b met 19:00–23:00**, then no evaluations. B: **R1 unknown** (no SAT); **R2a and R2b unknown until 05:10** (`insufficient_history`), **not_met from 05:15**; **R3 never met** for A or B (no inheritance either way) |
| 14 | SAT passed 19:30; checks confirm; norepinephrine **0.08 mcg/kg/min with weight missing** | **R1 unknown** all night (`weight_missing`; never a guessed weight) |
| 15 | **Deferral across midnight.** SAT passed 18:30; criteria hold; MD documents at 20:45 "deferred until 01:30" (reason, owner) | **R1 met 20:35–20:40** (prompt 1); **suppressed 20:45–01:25** (no reset at midnight); **met again at 01:30** (new episode, prompt 2); **unknown from 06:35** (SAT older than 12 h) |
| 16 | **Desaturation during tagged suctioning**: tag 03:00–03:10, FiO2 1.0; good-quality SpO2 96 → 82 at 03:00 and 03:05, back to 96 at 03:10 | **R2a met at 03:05** (the SpO2 branch is never suppressed by tags); not_met from 03:10 |
| 17 | **CRRT**: IV +6.0 L, CRRT net −3.5 L, gross effluent/replacement records present; **no urine output charted after 20 Nov 10:00** | **R2b unknown** all night (`output_not_charted`); the computed net is still shown: +4.25 L at 19:00, falling to +2.5 L once the 04:00 CRRT entry is known (gross CRRT volumes ignored) |

Not covered by a bed (unit tests at build time): the R1 context gate (RR > 35, pH < 7.30), the NMBA criterion, confirmation expiry on a vasoactive dose change, and unsupported units.
