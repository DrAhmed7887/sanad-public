# Sanad

> **FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE**

Sanad is an offline demonstration of sourced night-shift review rules and simulated notification workflows, replayed on a fixed fictional 17-bed adult ICU ward. A deterministic Python engine evaluates the scenarios; a self-contained HTML board lets a viewer step through the night in five-minute increments.

![Sanad workflow: fixed synthetic records are prepared and time-filtered, evaluated by four independent rule modules, then rendered as a precomputed offline nurse/doctor board. A Bed 6 example shows event time versus documentation time.](docs/workflow.png)

Workflow sources and portrait format: [landscape SVG](docs/workflow.svg) · [4:5 PNG](docs/workflow_4x5.png) · [4:5 SVG](docs/workflow_4x5.svg).

Built with Kiro for **Kiroween 2026, Frankenstein category**. The runtime uses the Python standard library, HTML, CSS and vanilla JavaScript; the generated board needs no server, account or network connection.

## Intended use

> Offline software demonstration using fictional adult ICU scenarios. Illustrates configurable rules and notification workflows. Not intended to monitor people, assess SBT readiness, detect deterioration, prioritise clinical care, or support diagnosis or treatment. Do not enter patient data. No clinical performance has been established.

The statement above is reproduced verbatim from the signed [rules baseline](docs/EVIDENCE.md).

## Scope and fixed-data limits

Sanad demonstrates software behaviour; it is not a clinical service.

- **Fixed synthetic input only:** [`data/ward_seed42/`](data/ward_seed42/) contains seed-42 data for **17 beds and 18 fictional encounters**. Bed 13 changes encounter during the night.
- **One fixed timeline:** 24 hours from 07:00 on 20 November 2026 to 07:00 on 21 November 2026 (`+01:00`): 12 hours of history followed by the displayed 19:00–07:00 night shift.
- **No patient-data path:** no patient-data entry, upload, import, external feed, live device connection or real notification recipient. Simulated actions use fixed buttons and picklists, remain in browser memory and reset on reload.
- **Offline replay:** the generated HTML embeds precomputed engine cells. Its JavaScript selects and displays those cells; it does not implement or recalculate a rule.
- **Visible limits:** the board uses `met`, `not_met`, `unknown`, `suppressed` and `not_applicable` with reason codes. Missing information is not treated as a negative result, and stale observations produce a visible feed alert rather than silence.
- **No clinical inference from the dataset:** the scenarios are hand-built to exercise configured logic. They cannot establish clinical sensitivity, specificity, performance, safety or benefit. R2a/R2b thresholds are explicitly **DESIGN demo values, not emergency alarm thresholds**.

See the [data card](data/DATA_CARD.md), [scenario oracle](data/SCENARIOS.md) and [rules baseline](docs/EVIDENCE.md) for the exact inputs, expected timings, sources and DESIGN rationales.

### Demonstration modules

| Module | Demonstrated logic |
|---|---|
| **R1 — SBT screen review candidate** | Configured criteria, duration, applicable pathways and one-prompt-per-episode behaviour. A match does not establish SBT or extubation readiness. |
| **R2a — oxygenation trend review** | Separate ventilator-settings and good-quality-SpO2 branches, evaluated independently of fluid balance. |
| **R2b — fluid-accounting review** | Rolling, deduplicated transaction accounting as known at the selected time; missing output is not treated as zero. |
| **R2 combined display** | An approved combined message when R2a and R2b are both `met`; it does not establish pulmonary oedema or indicate fluid removal. |
| **R3 — task and response tracker** | Per-encounter ventilation-check timing and a workflow kept separate from the evaluation state. Acknowledgement is not completion. |

## Generate and open the local demo

### Prerequisite

Use **Python 3.12**, available on `PATH` as `python3`. The engine and generator have no third-party runtime dependencies. Check the interpreter from the repository root before building:

```bash
python3 --version
```

If this does not report Python 3.12.x, select a Python 3.12 executable rather than using an older system interpreter.

### Generate

From the repository root:

```bash
PYTHONPATH=src python3 -m sanad.board --out dist/board.html
```

Do not add `-I` to this command: isolated mode drops the required `PYTHONPATH`, and the repository is not an installed package. The command reads the fixed dataset, evaluates the night grid and writes one self-contained UTF-8 HTML file. `dist/` is a local, git-ignored output directory.

### Open

Open `dist/board.html` directly in a desktop browser. No local server is needed. On macOS:

```bash
open dist/board.html
```

The Start screen shows the intended-use and verification statements, the persistent fictional/simulation label and the two role views.

## Judge-facing local walkthroughs

Start each flow by reloading the page to clear any simulated workflow overlays. Use **5 min →** and **← 5 min** to move on the fixed five-minute grid. Beds are ordered by bed number; doctor episodes are ordered by time raised, not severity or urgency.

### 1. Orientation, missing inputs and non-triggering text

1. Choose **Night nurse view**. The board starts at **19:00 on 20 Nov 2026** with 17 fictional bed tiles.
2. Inspect **Bed 2**: R1 is `unknown` with `sat_not_recorded`.
3. Inspect **Bed 7**: when no configured rule is `met`, the tile says `No configured rule triggered on the available data`.
4. Optionally inspect **Bed 14** for `unknown/weight_missing`; the demonstration does not guess a missing weight.

### 2. R1 review wording and source lines

1. Return to **Start**, choose **On-call doctor view**, and advance to **22:20**.
2. Open the **Bed 1 / R1** episode raised at 22:20.
3. The selected cell shows R1 `met`; the review panel shows the approved wording and eight static criterion/source rows (criteria 0, a–f and duration).
4. The rows expose the configured basis; this build does not display separate live states for each criterion.

### 3. Acknowledgement does not complete a check

1. Reload and choose **Night nurse view**; advance to **01:10**.
2. Open **Inbox: N open (simulated)** and select **Bed 10 / R3**. The ward-tile route reaches the same bed detail.
3. R3 is `met` and its workflow is `notified`.
4. Select **Acknowledge (simulated)**. The workflow changes to `acknowledged`; the R3 evaluation remains `met` because no new check was recorded by that action.

### 4. A stale feed remains visible

1. Reload and choose **Night nurse view**; advance to **01:15**.
2. The banner reads `feed alert · beds 9`, and Bed 9 has a visible feed chip.
3. Bed 9's observation-based R1 and R2a cells are `unknown` with `stale_data`. The failure is not folded into the non-triggering text.

### 5. Combined R2 review at the documentation boundary

1. Reload and choose **On-call doctor view**; advance to **02:00**.
2. Open the still-open **Bed 6 / R2** item.
3. R2a and R2b are both `met`, and the combined review message is visible.
4. The underlying fictional scenario includes a fluid transaction with event time 20:00 and documented time 02:00; the board changes only when that record becomes known. See [Bed 6 in the scenario oracle](data/SCENARIOS.md) for the expected timings.

### 6. Simulated deferral and reload reset

1. Reload and choose **On-call doctor view**; advance to **01:30**.
2. Open Bed 15's new R1 episode.
3. Keep a listed reason, choose owner **charge nurse** and until **01:30**, then select **Deferred (simulated)**.
4. The workflow chip reads `deferred · charge nurse · until 01:30`; the engine's R1 evaluation remains `met`.
5. Reload the page: the simulated workflow overlay is gone. Dataset-documented deferrals are distinct from these memory-only overlays and still replay from the precomputed cells.

## Architecture

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
| [`src/sanad/model.py`](src/sanad/model.py), [`states.py`](src/sanad/states.py) | Typed records/results, evaluation and workflow states, reason codes and approved text. |
| [`src/sanad/loader.py`](src/sanad/loader.py), [`units.py`](src/sanad/units.py) | Fixed-dataset loading, validation, FiO2 normalisation and dose conversion. |
| [`src/sanad/timeline.py`](src/sanad/timeline.py), [`freshness.py`](src/sanad/freshness.py) | As-known-at filtering, the five-minute grid, durations and stale-feed handling. |
| [`src/sanad/r1.py`](src/sanad/r1.py), [`r2a.py`](src/sanad/r2a.py), [`r2b.py`](src/sanad/r2b.py), [`r3.py`](src/sanad/r3.py) | Pure configured-rule evaluation, one module per demonstration module. |
| [`src/sanad/evaluate.py`](src/sanad/evaluate.py) | Whole-ward orchestration, combined R2 message and per-cell workflow/display output. |
| [`src/sanad/board.py`](src/sanad/board.py) | Deterministic board model, episode grouping, self-contained HTML generation and the display-only viewer. |

The generator has three explicit layers: `build_board_model` serialises engine results, `render_html` produces HTML, and `main` performs dataset loading and output-file writing. Rule modules do not import one another; orchestration owns cross-rule composition. Browser code uses the embedded result at the selected index instead of a second JavaScript implementation of the rules.

## Kiro specs and traceability

Kiro CLI implemented individual application tasks through a constrained custom builder. The root [`.kiro/`](.kiro/) directory is tracked and contains the implementation contract rather than relying on one open-ended application prompt.

- **Rules-engine spec:** [requirements](.kiro/specs/rules-engine/requirements.md), [design](.kiro/specs/rules-engine/design.md) and [tasks](.kiro/specs/rules-engine/tasks.md) cover shared definitions, R1, R2a, R2b, combined R2, R3 and the whole-ward oracle.
- **Ward-board spec:** [requirements](.kiro/specs/ward-board/requirements.md), [design](.kiro/specs/ward-board/design.md) and [tasks](.kiro/specs/ward-board/tasks.md) cover the engine-backed model, offline HTML, display fidelity, navigation, ordering and simulated workflows.
- **Steering:** [product](.kiro/steering/product.md), [safety](.kiro/steering/safety.md) and [technology](.kiro/steering/tech.md) preserve scope, state distinctions, deterministic Python 3.12 and offline constraints.
- **Custom agent:** [`.kiro/agents/sanad-builder.json`](.kiro/agents/sanad-builder.json) grants file read/write tools without shell access and confines application writes to approved paths.
- **Hooks:** [`scripts/hooks/`](scripts/hooks/) contains the baseline hash check, protected-write guard and post-write banned-wording warning. The wording hook warns; it does not roll back a write.
- **Traceability:** [`docs/TRACE.md`](docs/TRACE.md) links criteria to source or DESIGN rationale, inputs and timing, scenario expectations, data checks, tests, implementation and public wording. [`docs/DECISIONS.md`](docs/DECISIONS.md) records reviewed decisions and amendments, including D28's display boundaries.

Requirements use EARS-style acceptance criteria. pytest and the scenario oracle check specific outcomes and timings; Hypothesis checks the baseline's 12 property invariants; Playwright drives the generated local `file://` page in Chromium with the browser context forced offline.

## Test setup and commands

Testing requires Python 3.12 plus the pinned development packages in [`requirements-dev.txt`](requirements-dev.txt). Playwright and Chromium are test-only dependencies; neither is required by the generated board.

From the repository root, using a Unix-like shell:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
```

Run the fixed-data checks and full test suite:

```bash
python3 -I data/check_data.py
python3 -m pytest -q
```

To reproduce seed 42 into a temporary directory and compare every generated file without modifying the tracked dataset:

```bash
python3 -I data/generate.py --seed 42 --out /tmp/sanad-ward-seed42
diff -r data/ward_seed42 /tmp/sanad-ward-seed42
```

GitHub Actions runs the equivalent data-reproducibility, data-check, secret/personal-pattern and full pytest gates in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Browser tests fail rather than skip if Chromium is unavailable.

## Verification vs validation

> Synthetic scenarios and automated checks exercise the demonstration's configured logic. They do not establish clinical performance, safety or benefit.

The statement above is reproduced verbatim from the [rules baseline](docs/EVIDENCE.md). AI review is not clinical validation.

### Release verification

The complete suite covers deterministic generation, scenario-oracle timings, unit and integration behaviour, 12 property-based invariants, offline/no-input HTML structure and executed-browser workflows. GitHub Actions runs the full suite on the public release; the Actions result and its commit SHA identify the exact software evidence. Those software checks must not be converted into clinical sensitivity, specificity, outcome, workload or safety claims.

## License

[MIT](LICENSE).
