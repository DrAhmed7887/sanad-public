# Sanad for judges

> **FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE**

Sanad is an offline demo of sourced night-shift review rules on a fixed fictional 17-bed adult ICU ward, built with Kiro for Kiroween 2026 (Frankenstein category). Nothing on this page is a clinical result.

**Headline (software behaviour on fictional data):** On the fixed fictional night, the rules were met 657 times; Sanad sent 11 messages: one per episode. 657 of 9,848 rule checks were `met`. The 11 messages are 9 for the on-call doctor (4 R1, 5 R2) and 2 for the night nurse (1 R3, 1 feed alert). Source: [`eval/results/alert-burden.json`](eval/results/alert-burden.json).

## Start here (under 5 minutes, no keys)

1. **See it:** open the [live board](https://drahmed7887.github.io/sanad-public/) → **On-call doctor view** → press **5 min →** until 22:20 → open the **Bed 1 / R1** message.
2. **Reproduce the headline** (Python 3.12, standard library only):

   ```bash
   python3 -I scripts/alert_burden.py --check
   ```

3. **Run every check:** `python3 -I data/check_data.py` and `python3 -m pytest -q` after the setup in the [README](README.md#test-setup-and-commands). GitHub Actions runs the same gates ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## The five Stage 2 criteria

Quoted from the official rules (kiroween.devpost.com/rules, read 7 Nov 2026); "..." marks text left out of that quotation.

### 1. Potential Impact

> "Does the project make a credible case for solving a real problem for a real audience? ... Would someone actually use this?"

| What Sanad shows | Proof |
|---|---|
| A real, sourced problem | README [Alert fatigue](README.md#alert-fatigue): an audible alarm burden of 187 per ICU bed per day (Drew et al. 2014, [doi:10.1371/journal.pone.0110274](https://doi.org/10.1371/journal.pone.0110274)); in primary care, 30% lower reminder acceptance for each additional reminder per encounter (Ancker et al. 2017, [doi:10.1186/s12911-017-0430-8](https://doi.org/10.1186/s12911-017-0430-8)) |
| A named audience: the night nurse and the on-call doctor | The two role views on the Start screen (`tests/test_board_viewer.py::test_start_screen_has_both_role_buttons`); routing in `board.NURSE_RULES` and `board.DOCTOR_RULES` ([`src/sanad/board.py`](src/sanad/board.py)) |
| What Sanad does about it, as a number | [`eval/results/alert-burden.json`](eval/results/alert-burden.json), written by [`scripts/alert_burden.py`](scripts/alert_burden.py) and re-checked against the engine by [`tests/test_alert_burden.py`](tests/test_alert_burden.py) |
| Rules a clinician can audit | [`docs/EVIDENCE.md`](docs/EVIDENCE.md): signed baseline v3, each rule with its published source or a DESIGN rationale; [`docs/TRACE.md`](docs/TRACE.md) links each criterion to its scenario, test and code |
| Would someone use it? | Not shown yet: no nurse or doctor has used it (backlog B1) |

### 2. Technological Implementation

> "How thoroughly and skillfully does the project use Kiro? ... Was a variety of Kiro tools used impactfully? ... Was there experimentation?"

| Kiro feature | Where | Proof |
|---|---|---|
| Spec-driven development: EARS requirements, design and tasks, one spec for the engine and one for the board | [`.kiro/specs/rules-engine/`](.kiro/specs/rules-engine/), [`.kiro/specs/ward-board/`](.kiro/specs/ward-board/) | All 20 tasks are checked off in the two `tasks.md` files; acceptance-criterion IDs (`AC-…`) are cited in the code and tests they drive |
| Steering: product, safety and technology | [`.kiro/steering/`](.kiro/steering/) | The approved wording is asserted verbatim by [`tests/test_board_wording.py`](tests/test_board_wording.py) |
| Custom agent: read and write tools only, no shell, path allow and deny lists | [`.kiro/agents/sanad-builder.json`](.kiro/agents/sanad-builder.json) | `toolsSettings.write` in the agent file |
| Agent hooks: `agentSpawn` baseline hash check, `preToolUse` frozen-file guard, `postToolUse` banned-wording scan | `hooks` in the agent file, scripts in [`scripts/hooks/`](scripts/hooks/) | [`tests/test_hooks.py`](tests/test_hooks.py) runs each hook as a subprocess |
| Property-based testing: the 12 invariants of the signed baseline, in Hypothesis | [`tests/test_pbt.py`](tests/test_pbt.py), with a derandomized profile in [`tests/conftest.py`](tests/conftest.py) | CI |
| Experimentation: an unattended Kiro CLI build loop | [`scripts/build_next.sh`](scripts/build_next.sh) runs Kiro headless on the next task, runs the tests and feeds failures and review findings back to Kiro; [`scripts/ship.sh`](scripts/ship.sh) merges only with green CI and an independent AI review | The two scripts; the per-task history is in the private build repository (backlog B6) |

Not claimed: MCP, Kiro powers, Kiro Crew, Kiro IDE or Kiro Web (backlog B7).

### 3. Design

> "Does the project deliver a complete, coherent product experience, not just a technical proof of concept?"

| What a judge can do | Proof |
|---|---|
| Open the whole board with no install, account or network | The [live board](https://drahmed7887.github.io/sanad-public/), or `dist/board.html` built locally (README [Generate and open the local demo](README.md#generate-and-open-the-local-demo)); [`tests/test_board_offline.py`](tests/test_board_offline.py): no external resources, no network or storage API, no data entry |
| Move through five screens in two roles: Start, Ward board, Bed detail, Inbox, Review prompt | [`docs/UI_FLOW.md`](docs/UI_FLOW.md); `board.SCREENS`; [`tests/test_board_viewer.py`](tests/test_board_viewer.py) |
| Follow six guided walkthroughs | README [Judge-facing local walkthroughs](README.md#judge-facing-local-walkthroughs); four of them (acknowledge, stale feed, combined R2, deferral) also run in headless Chromium in [`tests/test_board_browser.py`](tests/test_board_browser.py) |
| See honest states, never a reassuring silence | Five evaluation states with reason codes ([`src/sanad/states.py`](src/sanad/states.py)); PBT-10 in `tests/test_pbt.py`; no green and no banned words in `tests/test_board_wording.py` |
| Known display gap | Bed 13's first encounter still shows an R2 item in the doctor's list from 23:00 to 03:55, after it left (backlog B3) |

### 4. Innovation/Idea

> "How creative and novel is the concept ... Are any unusual technologies or public resources (like datasets) leveraged or combined in a unique way?"

| Element | Proof |
|---|---|
| The Frankenstein stitch: a source-linked clinical rule baseline, synthetic records with an event time and a documented time, a deterministic standard-library Python engine, a precomputed offline browser replay and simulated role workflows, held to one build by Kiro specs, steering, a constrained agent and hooks | [`docs/EVIDENCE.md`](docs/EVIDENCE.md), [`data/`](data/), [`src/sanad/`](src/sanad/), [`.kiro/`](.kiro/) |
| Published sources instead of guesses: each rule cites its source (for example the MODE protocol and the ATS/CHEST 2017 guideline) or is marked DESIGN | [`docs/EVIDENCE.md`](docs/EVIDENCE.md), frozen by hash in [`docs/BASELINE.md`](docs/BASELINE.md) and checked by `scripts/hooks/baseline_check.py` |
| "As known at" time: a record counts from its documented time and sits at its event time (Bed 6: fluids given at 20:00, documented at 02:00) | [`src/sanad/timeline.py`](src/sanad/timeline.py); PBT-6 `tests/test_pbt.py::test_pbt6_late_record_only_affects_at_or_after_its_doc_time`; `tests/test_combined.py::test_bed6_combined_message_absent_at_0155_present_at_0200` |
| The message burden is counted by the engine itself, not estimated | [`scripts/alert_burden.py`](scripts/alert_burden.py); [`tests/test_alert_burden.py`](tests/test_alert_burden.py) |
| Not used | No public dataset: every record is fictional (backlog B2) |

### 5. Presentation

> "Does the video clearly demonstrate the project working end-to-end? Does the pitch communicate what problem is solved, who it's for, and why it matters?"

| Element | Proof |
|---|---|
| What problem, for whom, why it matters | The README top (headline, workflow image, one run command) and its [Alert fatigue](README.md#alert-fatigue) and [Limits](README.md#limits) sections |
| Workflow diagram | [`docs/workflow.png`](docs/workflow.png) and [`docs/workflow.svg`](docs/workflow.svg), with 4:5 versions for posts |
| Demo video | Not published yet (backlog B5) |

## Open gaps (backlog)

| ID | Opened | Gap | Criterion | What would close it |
|---|---|---|---|---|
| B1 | 2026-11-10 | No real users, pilot or outside validation: every number is software behaviour on fictional data | Potential Impact | Walkthroughs with an ICU night nurse and an on-call doctor, with their feedback recorded |
| B2 | 2026-11-10 | The count comes from one fixed night (17 beds, hand-built scenarios); there is no second night, adversarial set or public dataset | Potential Impact, Innovation/Idea | More fictional nights, each counted by `scripts/alert_burden.py` and committed under `eval/results/` |
| B3 | 2026-11-10 | Bed 13's first encounter keeps R2b `met` for 60 grid points after its 23:00 discharge, so its R2 item stays in the doctor's list until 03:55 (108 grid points, 48 on board, in `doctor_episode_list`); [`data/SCENARIOS.md`](data/SCENARIOS.md) expects no evaluations after it leaves | Design | An engine fix with an oracle test, then a fresh `eval/results/alert-burden.json` (the 60 results are already outside the 657) |
| B4 | 2026-11-10 | The engine does not reject a deferral without a reason or an owner, and an R3 deferral without an expiry would not lapse (the fixed dataset has none) | Design | Validation in the loader or the rules, with tests |
| B5 | 2026-11-10 | The demo video is not published | Presentation | The film (under 3 minutes) on YouTube, linked here and in the README |
| B6 | 2026-11-10 | The public repository is a snapshot, so the per-task Kiro build history is not visible in it | Technological Implementation | A build log: each spec task, its date and its Kiro-built commit |
| B7 | 2026-11-10 | MCP, Kiro powers, Kiro Crew, Kiro IDE and Kiro Web were not used | Technological Implementation | Add one only where it fits the offline design |

## What is not claimed

No clinical performance, alert-fatigue effect, workload, time saving or safety benefit. The 657 is what a system that sent one message per `met` check would have sent on this night; no real product was run or compared. See the README [Limits](README.md#limits).
