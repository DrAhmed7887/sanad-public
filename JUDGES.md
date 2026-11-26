# Sanad for judges

> **FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE**

Sanad is an offline demo of sourced night-shift ICU review rules on a fixed fictional 17-bed ward, built with Kiro for Kiroween 2026 (Frankenstein category). Nothing here is a clinical result.

**Headline (fictional data):** Rules were met 657 times across 9,848 rule checks; Sanad sent 11 messages (9 on-call doctor: 4 R1, 5 R2; 2 night nurse: 1 R3, 1 feed alert). Source: [`eval/results/alert-burden.json`](eval/results/alert-burden.json).

## Verify in under 5 minutes (no keys)

Use these three links and commands to inspect the live UI, demo video, and reproducible checks.

1. **Watch & try:** [2:49 demo video](https://youtu.be/2LObw4ZvmOE) · [Live board](https://drahmed7887.github.io/sanad-public/) (1-click scenario jumps + custom-bed sandbox on Screen 1) · [Repository](https://github.com/DrAhmed7887/sanad-public).
2. **Reproduce the headline** (Python 3.12, stdlib only): `python3 -I scripts/alert_burden.py --check`
3. **Run all gates:** `python3 -I data/check_data.py && python3 -m pytest -q` (CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Stage 2 criteria summary

Full criterion-to-file mapping and backlog B1–B7 live in [`docs/JUDGING_GUIDE.md`](docs/JUDGING_GUIDE.md) and [`CLAIMS.md`](CLAIMS.md).

| Criterion | Primary proof |
|---|---|
| **Potential Impact** | Drew et al. 187 alarms/bed/day baseline ([`README.md`](README.md#alert-fatigue)); `eval/results/alert-burden.json`; signed rules [`docs/EVIDENCE.md`](docs/EVIDENCE.md). |
| **Technological Implementation** | Kiro specs ([`.kiro/specs/`](.kiro/specs/)), steering, custom builder agent ([`.kiro/agents/sanad-builder.json`](.kiro/agents/sanad-builder.json)), hooks ([`scripts/hooks/`](scripts/hooks/)), 12 Hypothesis PBTs ([`tests/test_pbt.py`](tests/test_pbt.py)). |
| **Design** | Single offline HTML (`src/sanad/board.py`), 5 keyboard-operable screens, 1-click scenario jumps, Screen-1 custom-bed sandbox, no reassuring silence (`tests/test_board_browser.py`, `tests/test_board_offline.py`). |
| **Innovation / Idea** | Source-linked rule baseline + bitemporal as-known-at timing (`src/sanad/timeline.py`) + engine-counted alert burden (`scripts/alert_burden.py`). |
| **Presentation** | [2:49 YouTube demo](https://youtu.be/2LObw4ZvmOE) (closes B5), workflow diagrams ([`docs/workflow.png`](docs/workflow.png)), and [`README.md`](README.md). |

## What is not claimed

No clinical performance, alert-fatigue reduction, workload saving, or patient-safety benefit is claimed. See [`README.md`](README.md#limits) and [`docs/JUDGING_GUIDE.md`](docs/JUDGING_GUIDE.md).
