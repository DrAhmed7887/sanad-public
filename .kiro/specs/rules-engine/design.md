# Design: Sanad rules engine

How `src/sanad/` satisfies `requirements.md`. Stdlib-only, deterministic, one module per rule (see `.kiro/steering/tech.md`). The engine reads the fixed dataset in `data/ward_seed42/` and writes nothing back to `docs/` or `data/`.

## 1. Module map

```
src/sanad/
  model.py       # dataclasses for records and results
  states.py      # EvaluationState, WorkflowState enums + ReasonCode
  loader.py      # read & validate ward.json + *.jsonl into typed records
  units.py       # FiO2 fraction/percent normalisation; dose conversion; unit errors
  timeline.py    # as-known-at-t views; 5-min grid; duration tracking (15-min gap rule)
  freshness.py   # 15-min freshness test; stale_data; feed alert
  r1.py          # SBT screen review candidate (0, a-f, duration, pathways, episodes)
  r2a.py         # oxygenation trend review (settings + SpO2 branches)
  r2b.py         # fluid-accounting review (72h rolling net, coverage, CRRT)
  r3.py          # task & response tracker (per-encounter vent check, workflow)
  evaluate.py    # orchestration over the grid; R2 combined message; silence text
```

Dependency direction: `model`/`states` → `units`/`loader` → `timeline`/`freshness` → `r1`/`r2a`/`r2b`/`r3` → `evaluate`. Rule modules import only shared modules, never each other. Every rule function is pure: `(context, t) -> RuleResult`.

## 2. Data types (`model.py`)

Records mirror `data/DATA_CARD.md` and the inspected JSONL fields:

- `Observation`: bed, encounter, t (event time), fio2 (+fio2_unit), peep (+peep_unit), spo2 (+spo2_quality), rr, sbp, hr, spont_effort_flag. (No pH in the dataset; R1-f pH is unit-test input only.)
- `Infusion`: bed, encounter, drug, dose, unit (`mcg/min`|`mcg/kg/min`|`units/min`), start, end.
- `Event` (tagged union by `type`): `sat` (result, t), `rass` (value, t), `vent_check` (performed_at, documented_at, effort, haemodynamics, cuff_pressure_cmH2O), `planned_change` (start, end, reason), `feed_status` (status, start, end), `deferral` (rule, until, reason, owner, t), `staff_action` (action e.g. acknowledge, by, rule, t), `admission`/`discharge` (t).
- `FluidTx`: bed, encounter, tx_id, kind (`in`|`out`), ml, source (`iv`|`urine`|`crrt_net`|`crrt_*_gross`), event_time, documented_time.
- `Encounter`: bed, encounter id, age, sex, weight_kg (nullable), code_status (`full`|`dnr`), pathways[], anuric, scenario.
- `DailyTotal`: distractor, loaded but never used by rules (asserted in tests).

Each record keeps **two times where they differ**: `event_time` (placement on the timeline) and `documented_time` (visibility gate for as-known-at). Times are tz-aware `datetime`. Fluid `ml` and durations are integers; FiO2 handled as `Decimal` to avoid float threshold error.

Result types:

- `RuleResult`: rule_id, state (EvaluationState), reason (ReasonCode), detail (named missing items / displayed agents / shown target / "fluid balance unknown"), message (approved wording when `met`), episode_id (optional).
- `GridCell`: bed, encounter, t, {rule_id → RuleResult}, combined_message (optional), feed_alert (bool), display_text (silence text when nothing met), workflow_state per open episode.

## 3. Enums and reason codes (`states.py`)

```
class EvaluationState(Enum):  MET, NOT_MET, UNKNOWN, SUPPRESSED, NOT_APPLICABLE
class WorkflowState(Enum):    IDLE, NOTIFIED, ACKNOWLEDGED, ASSESSED, DEFERRED, RESOLVED
```

`ReasonCode` (string enum) at least:
`sat_not_recorded`, `haemo_unconfirmed`, `weight_missing`, `context_review`, `nmba_infusing`, `confirmation_expired`, `twelve_h_ref_missing`, `stale_data`, `insufficient_history`, `output_not_charted`, `unsupported_unit`, `missing_item`, `pathway_excluded`, `held_deferred`, `acknowledged_open`, `ecmo`, `comfort_only`, `ok_not_met`, `no_rule_triggered`.

Invariants enforced centrally: `MET` is only ever returned by a rule when no mandatory input is missing/stale/unresolved (PBT-1); the silence text constant lives here and is the only text used when nothing is `met` (PBT-10, AC-DEF-4). Workflow transitions are a pure state machine that never mutates an `EvaluationState` (AC-DEF-2).

## 4. Loader (`loader.py`)

Reads `ward.json` (encounters) and the five JSONL files with stdlib `json`, line by line. Validates required fields, parses tz-aware times, rejects unknown unit strings early (feeds `units.py` error path). Returns a `Dataset` grouping records by encounter and by bed. Pure given file bytes; no network, isolated-mode safe. `daily_totals.jsonl` is loaded into `DailyTotal` only so tests can prove rules ignore it.

## 5. Units (`units.py`)

- `normalise_fio2(value, unit)`: `fraction` 0.21–1.0 passthrough; `percent` 21–100 → /100; out-of-range or other unit → `UnsupportedUnitError`. Equal fraction/percent give identical `Decimal` (AC-DEF-8, PBT-2). Handles bed 1 charting 0.40 and 40.
- `convert_dose(dose, unit, weight_kg)`: `mcg/min` passthrough; `mcg/kg/min` needs weight → multiply, else `WeightMissingError` (AC-DEF-9); `units/min` is an "other agent" flag, not a mcg threshold. Unsupported unit → error (AC-DEF-10, PBT-2). Bed 14 (0.08 mcg/kg/min, weight null) → `weight_missing`.

## 6. Timeline & as-known-at (`timeline.py`)

- `grid(start, end, step=5min)`: yields clock-aligned times (…:00, :05). The 5-minute evaluation grid is produced by flooring the encounter window to the step and iterating; the same grid is reused by every rule so results align for the combined message.
- `as_known_at(records, t)`: keeps records with `documented_time ≤ t`, orders by `event_time` (stable), so late documentation changes only evaluations at/after its documented time (AC-DEF-11, AC-R2b-asknown, PBT-6).
- `duration_held(predicate_times, t, min_minutes, max_gap=15min)`: walks fresh samples; a gap > 15 min restarts the clock; returns the sustained run length ending at t (AC-DEF-6). "More than N" vs "at least N" handled by strict/≥ comparison so R1 fires at the first grid point after 120 min and R2a branches at onset + 30/5 min.

## 7. Freshness (`freshness.py`)

`is_fresh(obs, t)` = `t - obs.event_time ≤ 15min`. `freshness_gate(bed, t)`: if the newest observation as-known-at t is > 15 min old, every observation-based rule returns `UNKNOWN`/`stale_data` and `feed_alert=True`; a `feed_status: down` event also raises the alert (AC-DEF-5, AC-R3-failure). Bed 9: unknown 01:15–02:25, fresh again 02:30 with duration clocks restarted.

## 8. Rule modules

- **r1.py** — evaluates criteria 0 and a–f on the window, each returning a sub-state; `unknown` on any missing mandatory item (named) dominates per PBT-1; `not_met` for recorded negatives and the R1-f gate; pathways → `not_applicable` (DNR excluded from exclusions); duration via `duration_held` (> 120 min); episode manager issues one prompt per episode and honours `deferral`/assessed → `suppressed` until expiry, re-evaluating with no midnight reset.
- **r2a.py** — settings branch (FiO2 ≥ 0.10 or PEEP ≥ 2 over the 6-h minimum **excluding tagged windows**, ≥ 30 min) and SpO2 branch (good-quality SpO2 ≥ 3 below 6-h good-quality median, ≥ 5 min, tags never suppress, target shown if present). `insufficient_history` < 6 h; `not_applicable` for ECMO/comfort-only; fires regardless of fluid, labels "fluid balance unknown" when fluids absent (PBT-5, PBT-12).
- **r2b.py** — 72-h rolling net as-known-at t, dedup by `tx_id`, summed by `event_time`, CRRT only `crrt_net` (gross ignored), no daily totals; `> +2000 ml` → `met`; `output_not_charted` when no urine/drain output in previous 6 h and not anuric; `insufficient_history` < 6 h; applies to ECMO (PBT-6).
- **r3.py** — per-encounter valid check = all three fields; due = last valid + 2 h, first due admission + 30 min; `met` (overdue) at due + 10 min grace inclusive; workflow machine keeps episode open through `acknowledge`, closes on valid check or documented deferral; never inherits across reassignment (PBT-7, PBT-8).

## 9. Orchestration (`evaluate.py`)

For each encounter and each grid time t: apply `freshness_gate`, then run R1/R2a/R2b/R3 on the as-known-at-t context, assemble a `GridCell`. When R2a and R2b are both `MET` at t, attach the combined message (AC-R2-comb). When no rule is `MET`, set `display_text` to the single silence constant (never safe/green). Emit per-bed, per-time results covering the night window (19:00–07:00) plus the pre-shift history needed for 6-h/12-h look-back. Output is a deterministic ordered structure the scenario-oracle tests index by `(bed, t)`.

## 10. Evaluation grid production (summary)

The 5-minute grid is generated once per run by `timeline.grid` over the dataset window, clock-aligned to :00/:05/... Every rule is evaluated at every grid point using `as_known_at(t)`, so: durations are measured in grid steps with the 15-min gap rule, freshness is checked per grid point, late-documented records only affect grid points ≥ their documented time, and the combined message and silence text are decided per grid point. This single shared grid is what lets oracle timings (e.g. "met from 22:20", "01:15–02:25") be asserted exactly.
