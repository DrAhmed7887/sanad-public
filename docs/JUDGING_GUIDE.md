# Judging criteria map and open backlog

This document maps the five Kiroween Stage 2 judging criteria (`kiroween.devpost.com/rules`, read November 7, 2026) to repository files, tests, and screens, and tracks open backlog gaps B1-B7.

## Stage 2 criteria

The tables below list the proof artifacts for each judging criterion.

### 1. Potential impact

Sanad targets alert fatigue for the night nurse and the on-call doctor.

| What Sanad shows | Proof |
|---|---|
| A real, sourced problem | Audible alarm burden of 187 per ICU bed per day (Drew et al. 2014, [doi:10.1371/journal.pone.0110274](https://doi.org/10.1371/journal.pone.0110274)); 30% lower reminder acceptance per additional reminder per encounter in primary care (Ancker et al. 2017, [doi:10.1186/s12911-017-0430-8](https://doi.org/10.1186/s12911-017-0430-8)). |
| A named audience: night nurse and on-call doctor | Two role views on Screen 1 (`tests/test_board_viewer.py::test_start_screen_has_both_role_buttons`); routing in `board.NURSE_RULES` and `board.DOCTOR_RULES` ([`src/sanad/board.py`](../src/sanad/board.py)). |
| Episode-grouped message count | [`eval/results/alert-burden.json`](../eval/results/alert-burden.json), written by [`scripts/alert_burden.py`](../scripts/alert_burden.py) and checked by [`tests/test_alert_burden.py`](../tests/test_alert_burden.py). |
| Rules a clinician can audit | [`docs/EVIDENCE.md`](EVIDENCE.md) (signed baseline v3) and [`docs/TRACE.md`](TRACE.md). |
| Real clinical use | Not shown yet: no nurse or doctor has used it (backlog B1). |

### 2. Technological implementation

Kiro CLI drove spec-guided development with constrained tools and automated hooks.

| Kiro feature | Where | Proof |
|---|---|---|
| Spec-driven development | [`.kiro/specs/rules-engine/`](../.kiro/specs/rules-engine/), [`.kiro/specs/ward-board/`](../.kiro/specs/ward-board/) | All 20 tasks checked off in both `tasks.md` files; `AC-...` IDs cited in code and tests. |
| Steering | [`.kiro/steering/`](../.kiro/steering/) | Approved wording asserted verbatim by [`tests/test_board_wording.py`](../tests/test_board_wording.py). |
| Custom agent | [`.kiro/agents/sanad-builder.json`](../.kiro/agents/sanad-builder.json) | Read/write tools only, no shell, explicit path allow and deny lists. |
| Agent hooks | [`scripts/hooks/`](../scripts/hooks/) | `agentSpawn` baseline hash check, `preToolUse` frozen guard, `postToolUse` banned-wording scan; tested in [`tests/test_hooks.py`](../tests/test_hooks.py). |
| Property-based testing | [`tests/test_pbt.py`](../tests/test_pbt.py), [`tests/conftest.py`](../tests/conftest.py) | 12 invariants of the signed baseline in Hypothesis, derandomized in CI. |
| Unattended build loop | [`scripts/build_next.sh`](../scripts/build_next.sh), [`scripts/ship.sh`](../scripts/ship.sh) | Headless Kiro task loop with CI and independent AI review gates (backlog B6). |

Not claimed: MCP, Kiro powers, Kiro Crew, Kiro IDE, or Kiro Web (backlog B7).

### 3. Design

The generated board is a single offline HTML file with keyboard accessibility, Screen-1 live status, one-click scenario jumps, and an interactive custom-bed sandbox.

| What a judge can do | Proof |
|---|---|
| Open without install, account, or network | [Live board](https://drahmed7887.github.io/sanad-public/) or `dist/board.html`; [`tests/test_board_offline.py`](../tests/test_board_offline.py). |
| Move through five screens in two roles | [`docs/UI_FLOW.md`](UI_FLOW.md); `board.SCREENS`; [`tests/test_board_viewer.py`](../tests/test_board_viewer.py). |
| Jump to key scenarios or test custom bed states | Three 1-click scenario jumps (`22:20`, `02:00`, `01:15`) and the Screen-1 custom-bed sandbox tested in [`tests/test_board_browser.py`](../tests/test_board_browser.py). |
| See honest states, never reassuring silence | Five states with reason codes ([`src/sanad/states.py`](../src/sanad/states.py)); PBT-10; no green and no banned words in [`tests/test_board_wording.py`](../tests/test_board_wording.py). |
| Known display gap | Bed 13's first encounter keeps an R2 item in the doctor's list from 23:00 to 03:55 after discharge (backlog B3). |

### 4. Innovation and idea

Sanad combines a source-linked rule baseline, as-known-at bitemporal records, a stdlib Python engine, and an offline replay and sandbox board.

| Element | Proof |
|---|---|
| Source-linked baseline | [`docs/EVIDENCE.md`](EVIDENCE.md) frozen by hash in [`docs/BASELINE.md`](BASELINE.md) and checked by `scripts/hooks/baseline_check.py`. |
| As-known-at time | [`src/sanad/timeline.py`](../src/sanad/timeline.py); PBT-6 and `tests/test_combined.py::test_bed6_combined_message_absent_at_0155_present_at_0200`. |
| Engine-counted burden | [`scripts/alert_burden.py`](../scripts/alert_burden.py); [`tests/test_alert_burden.py`](../tests/test_alert_burden.py). |
| Public dataset status | Every record is fictional (backlog B2). |

### 5. Presentation

Pitch materials link the demo video, workflow diagram, and reproducible counts.

| Element | Proof |
|---|---|
| Problem, audience, and limits | [README](../README.md) headline, workflow figure, alert-fatigue table, and limits. |
| Workflow diagram | [`docs/workflow.png`](workflow.png) and [`docs/workflow.svg`](workflow.svg) (plus 4:5 variants). |
| Demo video | [YouTube, 2:49](https://youtu.be/2LObw4ZvmOE). |

## Open gaps (backlog)

These gaps are open and documented for transparency.

| ID | Opened | Gap | Criterion | What would close it |
|---|---|---|---|---|
| B1 | 2026-11-10 | No real users, pilot, or outside validation: every number is software behavior on fictional data | Potential Impact | Walkthroughs with an ICU night nurse and an on-call doctor, with feedback recorded |
| B2 | 2026-11-10 | Count comes from one fixed night (17 beds, hand-built scenarios); no second night or public dataset | Potential Impact, Innovation/Idea | More fictional nights counted by `scripts/alert_burden.py` |
| B3 | 2026-11-10 | Bed 13's first encounter keeps R2b `met` for 60 grid points after 23:00 discharge (outside the 657 count) | Design | Engine fix with oracle test and refreshed `eval/results/alert-burden.json` |
| B4 | 2026-11-10 | Engine does not reject a deferral missing reason or owner, and an R3 deferral without expiry would not lapse | Design | Validation in loader or rules with tests |
| B5 | 2026-11-10 | ~~Demo video not published~~ Closed 2026-11-22: [YouTube (2:49)](https://youtu.be/2LObw4ZvmOE) | Presentation | Done: linked in README and `JUDGES.md` |
| B6 | 2026-11-10 | Snapshot repo hides per-task Kiro build history | Technological Implementation | Build log mapping each spec task to its date and commit |
| B7 | 2026-11-10 | MCP, Kiro powers, Kiro Crew, Kiro IDE, and Kiro Web were not used | Technological Implementation | Add one only where it fits the offline design |
