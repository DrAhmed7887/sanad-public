# Data card: Sanad synthetic ward (seed 42, rules baseline v3)

**Synthetic only.** 17 beds and 18 fictional adult ICU encounters on invasive ventilation (bed 13 changes patient at 23:00). The data cover 24 h (2026-11-20 07:00 to 2026-11-21 07:00, +01:00): 12 h of pre-shift history, then the night shift shown on the board. No real patient data was used, read or modelled from any individual. Not for clinical use.

## Files (`ward_seed42/`)
| File | Rows | What each row is |
|---|---|---|
| `ward.json` | 18 encounters | bed, encounter ID, age, sex, weight (kg), code status (`full` / `dnr`), pathways (e.g. `vv_ecmo`), scenario key, `fictional: true` |
| `observations.jsonl` | 4,893 | 5-min ventilator and monitor sample: FiO2 (+ unit `fraction` or `percent`), PEEP (cmH2O), SpO2 (+ `spo2_quality`), RR, spontaneous effort flag, SBP, HR |
| `infusions.jsonl` | 4 | continuous infusion: drug, dose, unit (`mcg/min`, `mcg/kg/min`, `units/min`), start, end |
| `events.jsonl` | 218 | SAT result, RASS, planned changes, feed status, deferral, admission/discharge, staff actions (acknowledge), 2-hourly ventilation checks (performed-at, documented-at, effort, haemodynamics, cuff pressure) |
| `fluids.jsonl` | 1,003 | one intake or output transaction: `tx_id`, encounter, kind, ml, source (`iv`, `urine`, `crrt_net`, `crrt_*_gross`), event time, documented time |
| `daily_totals.jsonl` | 84 | charting-day net balance that **resets at 07:00**: a distractor; rules must use transactions |

## How values were chosen
- Scenario values follow the frozen rules baseline v3 and its sources (`docs/EVIDENCE.md`): e.g. SBT screen thresholds from the MODE protocol (NCT05563779) and fluid-balance thresholds that are configurable DESIGN defaults (+2 L / 72 h).
- SpO2 is noise-free so that expected timings are exact; RR ±1, SBP −4..+5 and HR ±3 carry seeded noise. Illustrative, not drawn from any population distribution.
- Fluids are zero-net in/out pairs every 3 h (same timestamp, so a window edge never splits a pair) plus one scenario bolus on 20 Nov 08:00, so each bed's rolling 72-h net is exact (e.g. beds 4, 5, 7: +0.3, +3.2, +0.8 L; bed 6 +1.6 L, rising to +2.6 L when a late entry is documented at 02:00).

## Deliberate data problems (each tests a review finding)
FiO2 charted as 40 and 0.40 (bed 1); duplicate transaction IDs (beds 5, 6); an entry documented 6 h late (bed 6); poor-quality SpO2 artefact (bed 7); tagged pre-oxygenation (bed 8); an 85-minute feed outage (bed 9); a missed check plus an acknowledgement without assessment (bed 10); bed reassignment between encounters (bed 13); a weight-based dose with no weight (bed 14); a deferral across midnight (bed 15); desaturation during tagged suctioning (bed 16); CRRT gross volumes and missing urine output (bed 17); daily totals that reset at 07:00 (all beds).

## Reproduce and check
```
python3 -I data/generate.py --seed 42      # byte-identical on every run
python3 -I data/check_data.py              # 29 data checks against SCENARIOS.md; results in data/check_results.txt
```
Expected rule outcomes per bed are in `SCENARIOS.md`; they were written before the generator and are the build's test oracle.

## Limits
Seventeen hand-built scenarios cannot establish clinical sensitivity or specificity. These data checks confirm the inputs only; once the rules engine is built, its tests will exercise the configured logic. Neither shows the rules are clinically safe or effective.
