# Architecture, specs, and verification

This document holds the detailed module breakdown, Kiro traceability references, and test setup instructions moved from the root README.

## Pipeline and modules

Sanad runs an offline deterministic pipeline from fixed synthetic ward data to a self-contained HTML board.

```text
data/ward_seed42/                         fixed synthetic records
        |
        v
loader.py -> units.py / timeline.py / freshness.py
        |
        v
r1.py   r2a.py   r2b.py   r3.py           independent rule modules
        |
        v
evaluate.py                               five-minute ward evaluation
        |
        v
board.py: build_board_model -> render_html
        |
        v
dist/board.html                           inline CSS + JSON + vanilla JS
                                          display and workflow replay only
```

| Area | Responsibility |
|---|---|
| [`src/sanad/model.py`](../src/sanad/model.py), [`states.py`](../src/sanad/states.py) | Typed records and results, evaluation and workflow states, reason codes, and approved text. |
| [`src/sanad/loader.py`](../src/sanad/loader.py), [`units.py`](../src/sanad/units.py) | Fixed-dataset loading, validation, FiO2 normalization, and dose conversion. |
| [`src/sanad/timeline.py`](../src/sanad/timeline.py), [`freshness.py`](../src/sanad/freshness.py) | As-known-at filtering, the five-minute grid, durations, and stale-feed handling. |
| [`src/sanad/r1.py`](../src/sanad/r1.py), [`r2a.py`](../src/sanad/r2a.py), [`r2b.py`](../src/sanad/r2b.py), [`r3.py`](../src/sanad/r3.py) | Pure configured-rule evaluation, one module per demonstration module. |
| [`src/sanad/evaluate.py`](../src/sanad/evaluate.py) | Whole-ward orchestration, combined R2 message, and per-cell workflow/display output. |
| [`src/sanad/board.py`](../src/sanad/board.py) | Deterministic board model, episode grouping, self-contained HTML generation, and the display-only viewer. |

The generator has three explicit layers: `build_board_model` serializes engine results, `render_html` produces HTML, and `main` performs dataset loading and output-file writing. Rule modules do not import one another; orchestration owns cross-rule composition.

## Demonstration modules

Each demonstration module exercises one configured rule family on synthetic records.

| Module | Demonstrated logic |
|---|---|
| **R1 — SBT screen review candidate** | Configured criteria, duration, applicable pathways, and one-prompt-per-episode behavior. A match does not establish SBT or extubation readiness. |
| **R2a — oxygenation trend review** | Separate ventilator-settings and good-quality-SpO2 branches, evaluated independently of fluid balance. |
| **R2b — fluid-accounting review** | Rolling, deduplicated transaction accounting as known at the selected time; missing output is not treated as zero. |
| **R2 combined display** | An approved combined message when R2a and R2b are both `met`; it does not establish pulmonary edema or indicate fluid removal. |
| **R3 — task and response tracker** | Per-encounter ventilation-check timing and a workflow kept separate from the evaluation state. Acknowledgement is not completion. |

## Kiro specs and traceability

Kiro CLI implemented individual application tasks through a constrained custom builder. The root [`.kiro/`](../.kiro/) directory is tracked and holds the implementation contract.

- **Rules-engine spec:** [requirements](../.kiro/specs/rules-engine/requirements.md), [design](../.kiro/specs/rules-engine/design.md), and [tasks](../.kiro/specs/rules-engine/tasks.md) cover shared definitions, R1, R2a, R2b, combined R2, R3, and the whole-ward oracle.
- **Ward-board spec:** [requirements](../.kiro/specs/ward-board/requirements.md), [design](../.kiro/specs/ward-board/design.md), and [tasks](../.kiro/specs/ward-board/tasks.md) cover the engine-backed model, offline HTML, display fidelity, navigation, ordering, and simulated workflows.
- **Steering:** [product](../.kiro/steering/product.md), [safety](../.kiro/steering/safety.md), and [technology](../.kiro/steering/tech.md) preserve scope, state distinctions, deterministic Python 3.12, and offline constraints.
- **Custom agent:** [`.kiro/agents/sanad-builder.json`](../.kiro/agents/sanad-builder.json) grants file read/write tools without shell access and confines application writes to approved paths.
- **Hooks:** [`scripts/hooks/`](../scripts/hooks/) contains the baseline hash check, protected-write guard, and post-write banned-wording warning.
- **Traceability:** [`docs/TRACE.md`](TRACE.md) links criteria to source or DESIGN rationale, inputs and timing, scenario expectations, data checks, tests, implementation, and public wording. [`docs/DECISIONS.md`](DECISIONS.md) records reviewed decisions and amendments, including D28 and D30.

## Test setup and CI verification

Testing requires Python 3.12 plus the pinned development packages in [`requirements-dev.txt`](../requirements-dev.txt). Playwright and Chromium are test-only dependencies; neither is required by the generated board.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
python3 -I data/check_data.py
python3 -I scripts/alert_burden.py --check
python3 -m pytest -q
```

To reproduce seed 42 into a temporary directory and compare every generated file without modifying the tracked dataset:

```bash
python3 -I data/generate.py --seed 42 --out /tmp/sanad-ward-seed42
diff -r data/ward_seed42 /tmp/sanad-ward-seed42
```

GitHub Actions runs the equivalent data-reproducibility, data-check, secret/personal-pattern, and full pytest gates in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), and builds and deploys the live board in [`.github/workflows/pages.yml`](../.github/workflows/pages.yml).

### Release verification

The complete suite covers deterministic generation, scenario-oracle timings, unit and integration behavior, 12 property-based invariants, offline/no-input HTML structure, and executed-browser workflows. GitHub Actions runs the full suite on [`DrAhmed7887/sanad-public`](https://github.com/DrAhmed7887/sanad-public); the Actions result and its commit SHA identify the exact software evidence. Those software checks must not be converted into clinical sensitivity, specificity, outcome, workload, or safety claims.

Synthetic scenarios and automated checks exercise the demonstration's configured logic. They do not establish clinical performance, safety, or benefit.
