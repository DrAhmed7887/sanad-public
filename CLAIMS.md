# Claims map

Each number or feature word in the README, JUDGES.md and the Kiroween submission, mapped to a file and the script that reproduces it. All figures are software behaviour on fictional data. No clinical performance has been established.

| Claim | File | Reproduce with |
|---|---|---|
| Rules met 657 times in 9,848 rule checks | `eval/results/alert-burden.json` | `python3 scripts/alert_burden.py --check` |
| 11 messages: 9 doctor (4 R1, 5 R2), 2 nurse (1 R3, 1 feed alert) | `eval/results/alert-burden.json` | `python3 scripts/alert_burden.py --check` |
| Synthetic ward, 17 beds, 18 encounters, seed 42, byte-identical | `data/DATA_CARD.md`, `data/generate.py` | `python3 -I data/generate.py --seed 42` |
| 29 data checks pass | `data/check_data.py`, `data/check_results.txt` | `python3 data/check_data.py` |
| Test suite, including 12 property-based invariants | `tests/test_pbt.py`, `tests/conftest.py` | `pytest` (CI: `.github/workflows/ci.yml`) |
| Five evaluation states, no reassuring silence | `src/sanad/states.py`, `tests/test_board_wording.py` | `pytest tests/test_board_wording.py` |
| Board works offline, no network, no data entry | `tests/test_board_offline.py` | `pytest tests/test_board_offline.py` |
| Late records count from their documented time | `src/sanad/timeline.py`, `tests/test_combined.py` | `pytest tests/test_combined.py` |
| Rules cite sources or are marked DESIGN; baseline frozen by hash | `docs/EVIDENCE.md`, `docs/BASELINE.md`, `scripts/hooks/baseline_check.py` | `python3 scripts/hooks/baseline_check.py` |
| Spec-driven development with Kiro | `.kiro/specs/rules-engine/`, `.kiro/specs/ward-board/` | read the `tasks.md` files |
| Known limits (B1 to B7) | `JUDGES.md` | read the limits table |

Published sources quoted in the README (Drew 2014, Ancker 2017, Aiken 2014) are cited there with DOI or PMID; they are literature, not results of this repository.
