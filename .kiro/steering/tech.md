# Tech steering: Sanad rules engine

Constraints the engine and its tests must obey. These are build rules, not clinical rules; the clinical baseline is `docs/EVIDENCE.md`.

## Language and runtime

- **Python 3.12**, **standard library only** for the engine package `src/sanad/`.
- **No third-party runtime dependencies.** The shipped engine imports only the Python standard library (e.g. `json`, `datetime`, `dataclasses`, `enum`, `decimal`, `bisect`, `pathlib`, `typing`). If a capability seems to need a third-party package, redesign to use the stdlib or raise it as a decision.
- **No network calls** anywhere in the engine or tests: no sockets, no HTTP, no DNS, no external feeds, no telemetry. The engine reads only the local fixed dataset under `data/ward_seed42/`.
- Run everything with isolated mode (`python3 -I`) as `CLAUDE.md` and the data card do, so user site-packages and env vars cannot leak in.

## Determinism

- The engine is **deterministic**: identical inputs always produce identical outputs, independent of wall-clock time, machine, locale, dict/iteration order, filesystem order, or run count.
- Evaluation time `t` is always an explicit input, never `datetime.now()`.
- All times are timezone-aware (`+01:00` in the dataset); never rely on the local zone.
- Use exact arithmetic where rounding would bias a threshold (prefer integers in ml/minutes; use `decimal.Decimal` or careful integer maths for FiO2 fraction/percent normalisation and weight-based dose conversion). No float equality on thresholds.
- Sort or canonicalise any collection before reducing over it, so record order, duplicate transaction IDs and day resets cannot change a result (property invariant 6).

## Structure: one module per rule

Package `src/sanad/` — each rule is its own module with a pure evaluation function; shared machinery is factored into small modules:

- `loader.py` — read and validate the JSONL/JSON dataset into typed records.
- `units.py` — FiO2 fraction/percent normalisation, weight-based dose conversion, unsupported-unit errors.
- `timeline.py` — "as known at time t" view and the 5-minute evaluation grid; durations with the 15-min gap rule.
- `freshness.py` — 15-min freshness test and the feed/stale-data alert.
- `r1.py` — SBT screen review candidate (criteria 0, a–f, duration, pathways, episodes).
- `r2a.py` — oxygenation trend review (settings branch + SpO2 branch).
- `r2b.py` — fluid-accounting review (rolling 72-h net, coverage, CRRT).
- `r3.py` — task and response tracker (per-encounter ventilation check, workflow states).
- `evaluate.py` — orchestrates the rules on the grid, produces per-bed/per-time results and the R2 combined message.
- `states.py` — the evaluation-state and workflow-state enums and reason codes (shared).
- `model.py` — dataclasses for records and results.

Rules must not import each other except through shared modules; `evaluate.py` may import all rule modules. Each rule function is **pure** (inputs → result, no I/O, no mutation of inputs).

## Tests

- **pytest** for scenario-oracle and unit tests; **hypothesis** for the 12 property-based invariants. Tests live in `tests/`.
- Test-only tooling (pytest, hypothesis and Playwright for executed-browser contract tests) is declared in `requirements-dev.txt`, never imported by `src/sanad/`. Browser tests open only the generated local `file://` HTML with Chromium's context forced offline; browser installation is CI setup, not a product or test-page network call.
- Scenario-oracle tests assert the engine's output against the per-bed expectations in `data/SCENARIOS.md` (the frozen oracle), on the 5-minute grid.
- Property-based tests encode invariants 1–12 from `docs/EVIDENCE.md`; strategies generate synthetic records only (no real data, no network).
- Hypothesis must be deterministic in CI: pin a seed/profile and keep examples reproducible; no `@example` depending on time.
- A test is "passed" only after it has run against the identified build (see verification-vs-validation wording).

## Repository and build loop

- Work on a branch `build/<short-name>`; never push directly to `main`.
- Before any push: `python3 -I data/check_data.py` and the full test suite must be green. Never push a red build.
- `.kiro/` is never gitignored. Real data, secrets and personal information are never committed (new commits use the noreply email per D25).
- GitHub CI (`.github/workflows/ci.yml`) must pass; an independent AI reviewer (different model from the builder) must APPROVE before squash-merge.

## Kiro agent and hooks

The unattended build loop runs the custom agent `.kiro/agents/sanad-builder.json` (Kiro 3.x config). It has file read/write only (no shell, matching `scripts/build_next.sh`), writes confined to `src/sanad/**`, `tests/**` and `docs/TRACE.md`, and loads CLAUDE.md, the steering files and the spec files as context. Three stdlib-only hooks (run as `python3 -I`, under `scripts/hooks/`) enforce the baseline:

- `baseline_check.py` (agentSpawn): recomputes SHA-256 of the frozen clinical files (docs/EVIDENCE.md, data/SCENARIOS.md, data/DATA_CARD.md, data/generate.py, data/check_data.py, data/check_results.txt and data/ward_seed42/*) and confirms they match the prefixes in docs/BASELINE.md; it exits non-zero if any drifted. It does not check docs/DECISIONS.md or docs/TRACE.md (those change after v3).
- `guard_frozen.py` (preToolUse on writes): reads the event JSON and blocks (exit 2) any write to a frozen file, docs/UI_FLOW.md or a `.kiro/specs/*/requirements.md`, explaining why; every other path is allowed.
- `wording_guard.py` (postToolUse on writes): parses the banned public phrases from docs/EVIDENCE.md (never hard-coded) and, for files under src/ or ending in .html/.md, reports any hit on STDERR so the agent fixes the wording.

The hooks never write files and make no network calls; `tests/test_hooks.py` exercises all three as subprocesses and asserts these properties.
