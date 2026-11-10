# Tasks: Sanad rules engine

Small, ordered implementation tasks. Each is a branch `build/<short-name>`; code is written from `design.md` to satisfy the listed requirement IDs; every task is green locally (`python3 -I data/check_data.py` + `pytest`) before it ships. Scenario-oracle tests assert against the per-bed expectations in `data/SCENARIOS.md`; property tests use hypothesis. Update `docs/TRACE.md` (test + code columns) in the same PR. Do not touch `docs/EVIDENCE.md`, `data/SCENARIOS.md`, `data/generate.py` or `data/ward_seed42/`.

- [x] 1. Loader, units and shared types
  - Files: `src/sanad/model.py`, `src/sanad/states.py`, `src/sanad/loader.py`, `src/sanad/units.py`
  - Requirements: AC-DEF-1, AC-DEF-7, AC-DEF-8, AC-DEF-9, AC-DEF-10
  - Tests: `tests/test_loader.py` (loads all 18 encounters + 5 record files; `daily_totals` loaded but flagged unused), `tests/test_units.py` (bed-1 FiO2 40 == 0.40; bed-14 mcg/kg/min + null weight → `weight_missing`; unsupported unit → explicit error) + PBT-2 (`tests/test_pbt.py`).

- [x] 2. Timeline, as-known-at, durations and freshness
  - Files: `src/sanad/timeline.py`, `src/sanad/freshness.py`
  - Requirements: AC-DEF-3, AC-DEF-5, AC-DEF-6, AC-DEF-11
  - Tests: `tests/test_timeline.py` (5-min grid alignment; as-known-at hides late docs; 15-min gap restarts the clock), `tests/test_freshness.py` (bed 9 stale 01:15–02:25, feed alert, fresh from 02:30) + PBT-1, PBT-6, PBT-9.

- [x] 3. R1 — SBT screen review candidate
  - Files: `src/sanad/r1.py`
  - Requirements: AC-R1-wording, R1-0, R1-a, R1-b, R1-c, R1-d, R1-e, R1-f, R1-⏱ (duration), R1-pathways, R1-episodes, AC-DEF-12
  - Tests: `tests/test_r1.py` oracle beds 1 (met 22:20, one prompt), 2 (`sat_not_recorded`), 3 (vasopressin → `haemo_unconfirmed`, both agents shown), 11 (`not_applicable`), 12 (DNR met 23:05), 14 (`weight_missing`), 15 (met 20:35, suppressed 20:45–01:25, met 01:30, unknown from 06:35); unit tests for R1-c NMBA, R1-f gate (RR>35, pH<7.30), confirmation expiry on dose change, unsupported unit + PBT-3, PBT-4, PBT-11.

- [x] 4. R2a — oxygenation trend review
  - Files: `src/sanad/r2a.py`
  - Requirements: AC-R2a-na, AC-R2a-hist, AC-R2a-settings, AC-R2a-spo2, AC-R2a-quality, AC-R2a-tags-spo2, AC-R2a-fluid-independent
  - Tests: `tests/test_r2a.py` oracle beds 4 (met 02:20; settings branch 02:50), 6 (met 01:05), 7 (not_met, artefact ignored), 8 (not_met, tagged pre-oxygenation), 11 (`not_applicable`), 16 (met 03:05 during tagged suctioning) + PBT-5, PBT-12.

- [x] 5. R2b — fluid-accounting review
  - Files: `src/sanad/r2b.py`
  - Requirements: AC-R2b-balance, AC-R2b-asknown, AC-R2b-dedup-order, AC-R2b-coverage, AC-R2b-crrt, AC-R2b-no-dailytotals, AC-R2b-hist, AC-R2b-pathways
  - Tests: `tests/test_r2b.py` oracle beds 4 (not_met +0.3 L), 5 (met, duplicate tx_ids), 6 (not_met until 01:55, met from 02:00 as-known-at), 11 (not_met, applies to ECMO), 13A (met 19:00–23:00), 17 (`output_not_charted`; net +4.25 L → +2.5 L, gross CRRT ignored) + PBT-6 (day-reset / order / dedup invariance; late record only affects t ≥ documented).

- [x] 6. R2 combined message
  - Files: `src/sanad/evaluate.py` (combined-message assembly on the shared grid)
  - Requirements: AC-R2-comb, AC-DEF-3, AC-DEF-4
  - Tests: `tests/test_combined.py` oracle bed 6 (combined message from 02:00 when R2a met 01:05 and R2b met 02:00); silence beds render "No configured rule triggered on the available data", never safe/green + PBT-10.

- [x] 7. R3 — task and response tracker
  - Files: `src/sanad/r3.py`
  - Requirements: AC-R3-valid, AC-R3-due, AC-R3-overdue, AC-R3-workflow, AC-R3-encounter, AC-R3-failure, AC-DEF-2
  - Tests: `tests/test_r3.py` oracle bed 10 (met 01:10–01:50; acknowledge keeps it met; not_met from 01:55 resolved), bed 13 (A and B never met via inheritance; first check due admission + 30 min); feed/routing failure shown as its own alert + PBT-7, PBT-8.

- [x] 8. End-to-end oracle over all 17 beds
  - Files: `src/sanad/evaluate.py` (orchestration), `tests/test_oracle_all_beds.py`
  - Requirements: all of the above (full `requirements.md`) plus AC-DEF-4 silence rendering
  - Tests: parametrised scenario-oracle test driving `evaluate` over the whole night window and asserting every bed's expected outcomes and timings in `data/SCENARIOS.md` (beds 1–17, including bed 13 A/B); confirms `daily_totals.jsonl` is never used and that the full 5-min grid is produced deterministically (re-run → identical output) + PBT-10 across all beds.
