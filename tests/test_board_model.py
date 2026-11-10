"""Tests for the board model (tasks.md task 1).

:func:`sanad.board.build_board_model` must serialise the engine's ward
evaluation **without recomputing anything**: for every grid point, the model's
cell ``state`` / ``reason`` / ``message`` must equal the
:class:`~sanad.model.GridCell` that :func:`sanad.evaluate.evaluate_ward`
produced (AC-GEN-6, AC-FID-1). This module has two parts:

* **scenario-oracle tests** over the real fixed dataset: the board model is
  built from ``evaluate_ward`` and every embedded cell is checked field-for-
  field against the corresponding ``GridCell``; the structural rules (grid
  times, bed ordering, episode/inbox ordering, bed 13's two encounters, enum
  ``.value`` serialisation, static copy) are asserted against the oracle
  (``data/SCENARIOS.md``) and the engine;
* **property-based tests** (hypothesis) over *synthetic* ward results: for any
  combination of evaluation states / reason codes / workflow states, the
  serialised cell round-trips to the same enum ``.value`` words, the beds stay
  in bed-number order and the episodes/inbox stay in time-raised order
  (determinism; no real data, no network -- ``.kiro/steering/tech.md``).

Reads the fixed dataset read-only (safety steering); never writes to ``docs/``
or ``data/``.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sanad import board
from sanad.evaluate import (
    R1_RULE_ID,
    R2A_RULE_ID,
    R2B_RULE_ID,
    R3_RULE_ID,
    evaluate_ward,
    night_window,
)
from sanad.loader import load_dataset
from sanad.model import Dataset, Encounter, GridCell, RuleResult
from sanad.states import (
    R1_MET_TEXT,
    R2_COMBINED_TEXT,
    R3_OVERDUE_TEXT,
    SILENCE_TEXT,
    EvaluationState,
    ReasonCode,
    WorkflowState,
)

TZ = timezone(timedelta(hours=1))
RULE_IDS = (R1_RULE_ID, R2A_RULE_ID, R2B_RULE_ID, R3_RULE_ID)


# ==========================================================================
# Fixtures: the real dataset, its ward evaluation, and the board model.
# ==========================================================================


@pytest.fixture(scope="module")
def ds(dataset) -> Dataset:
    return dataset


@pytest.fixture(scope="module")
def ward(ward_eval: dict) -> dict:
    return ward_eval  # shared session evaluation (tests/conftest.py)


@pytest.fixture(scope="module")
def model(ds: Dataset, ward: dict) -> dict:
    # Pass the precomputed ward so the model is checked against the *same*
    # GridCells the oracle tests read (and so the test does not re-run the
    # whole engine a second time).
    return board.build_board_model(ds, ward)


def _model_cells_by_encounter(model: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for bed in model["beds"]:
        for encounter, payload in bed["encounters"].items():
            out[encounter] = payload["cells"]
    return out


# ==========================================================================
# Structure: grid times, bed ordering, bed 13's two encounters.
# ==========================================================================


def test_grid_times_is_the_full_five_minute_grid(ds: Dataset, model: dict) -> None:
    start, end = night_window(ds)
    # 19:00..07:00 inclusive on a 5-min grid: 145 points.
    assert len(model["grid_times"]) == 145
    assert model["grid_times"][0] == start.isoformat()
    assert model["grid_times"][-1] == end.isoformat()
    # Strictly 5-minute ascending steps.
    times = [datetime.fromisoformat(s) for s in model["grid_times"]]
    for earlier, later in zip(times, times[1:]):
        assert later - earlier == timedelta(minutes=5)


def test_beds_are_ordered_by_bed_number(model: dict) -> None:
    numbers = [bed["bed"] for bed in model["beds"]]
    assert numbers == sorted(numbers)
    # 17 physical beds in the fixed ward.
    assert numbers == list(range(1, 18))


def test_bed_13_carries_both_encounters(model: dict) -> None:
    bed13 = next(b for b in model["beds"] if b["bed"] == 13)
    assert set(bed13["encounters"]) == {"E13A-1120", "E13B-1120"}
    # Every other bed has exactly one encounter.
    for bed in model["beds"]:
        if bed["bed"] != 13:
            assert len(bed["encounters"]) == 1


def test_every_encounter_is_present_on_the_full_grid(ds: Dataset, model: dict) -> None:
    cells_by_enc = _model_cells_by_encounter(model)
    assert set(cells_by_enc) == {e.encounter for e in ds.encounters}
    assert len(cells_by_enc) == 18  # 17 beds, bed 13 has A and B
    for encounter, cells in cells_by_enc.items():
        assert [c["t"] for c in cells] == model["grid_times"], encounter


# ==========================================================================
# Fidelity: every embedded cell equals the engine's GridCell (no recompute).
# ==========================================================================


def test_every_cell_equals_the_engine_grid_cell(ward: dict, model: dict) -> None:
    """For every grid point of every encounter, the serialised cell's
    state/reason/message/detail/workflow equal the GridCell verbatim."""

    cells_by_enc = _model_cells_by_encounter(model)
    for encounter, grid_cells in ward.items():
        model_cells = cells_by_enc[encounter]
        assert len(model_cells) == len(grid_cells), encounter
        for mcell, gcell in zip(model_cells, grid_cells):
            assert mcell["bed"] == gcell.bed
            assert mcell["encounter"] == gcell.encounter
            assert mcell["t"] == gcell.t.isoformat()
            assert mcell["combined_message"] == gcell.combined_message
            assert mcell["feed_alert"] == gcell.feed_alert
            assert mcell["display_text"] == gcell.display_text
            # Per-rule results, copied verbatim (state/reason as .value words).
            for rule_id in RULE_IDS:
                if rule_id not in gcell.results:
                    continue
                gr = gcell.results[rule_id]
                mr = mcell["results"][rule_id]
                assert mr["rule_id"] == gr.rule_id
                assert mr["state"] == gr.state.value
                assert mr["reason"] == gr.reason.value
                assert mr["detail"] == gr.detail
                assert mr["message"] == gr.message
                assert mr["episode_id"] == gr.episode_id
            # Workflow states serialise to their .value words.
            for rule_id, ws in gcell.workflow_states.items():
                assert mcell["workflow_states"][rule_id] == ws.value


def test_enums_serialise_to_verbatim_value_words(model: dict) -> None:
    """Every state/reason/workflow string in the model is a verbatim enum
    value word (never a relabelled or title-cased variant)."""

    valid_states = {s.value for s in EvaluationState}
    valid_reasons = {r.value for r in ReasonCode}
    valid_workflow = {w.value for w in WorkflowState}
    cells_by_enc = _model_cells_by_encounter(model)
    for cells in cells_by_enc.values():
        for cell in cells:
            for result in cell["results"].values():
                assert result["state"] in valid_states
                assert result["reason"] in valid_reasons
            for ws in cell["workflow_states"].values():
                assert ws in valid_workflow


# ==========================================================================
# Oracle sample points: the embedded cells match data/SCENARIOS.md.
# ==========================================================================


def _cell_at(model_cells: list[dict], iso: str) -> dict:
    return next(c for c in model_cells if c["t"] == iso)


def test_oracle_sample_points(model: dict) -> None:
    cells_by_enc = _model_cells_by_encounter(model)

    def at(enc: str, d: int, h: int, mi: int) -> dict:
        iso = datetime(2026, 11, d, h, mi, tzinfo=TZ).isoformat()
        return _cell_at(cells_by_enc[enc], iso)

    # Bed 1: R1 met from 22:20 with the approved sentence verbatim.
    assert at("E01-1120", 20, 22, 20)["results"]["R1"]["state"] == "met"
    assert at("E01-1120", 20, 22, 20)["results"]["R1"]["message"] == R1_MET_TEXT
    assert at("E01-1120", 20, 22, 15)["results"]["R1"]["state"] != "met"

    # Bed 6: combined R2 message from 02:00, empty before.
    assert at("E06-1120", 21, 1, 55)["combined_message"] == ""
    assert at("E06-1120", 21, 2, 0)["combined_message"] == R2_COMBINED_TEXT

    # Bed 9: feed alert true and observation rules unknown (stale_data) at 01:15.
    cell9 = at("E09-1120", 21, 1, 15)
    assert cell9["feed_alert"] is True
    assert cell9["results"]["R1"]["state"] == "unknown"
    assert cell9["results"]["R1"]["reason"] == "stale_data"
    assert cell9["results"]["R2a"]["state"] == "unknown"
    assert cell9["results"]["R2a"]["reason"] == "stale_data"
    # Fresh again from 02:30: no feed alert.
    assert at("E09-1120", 21, 2, 30)["feed_alert"] is False

    # Bed 10: R3 met (overdue) at 01:10 with the overdue text; not_met from 01:55.
    assert at("E10-1120", 21, 1, 10)["results"]["R3"]["state"] == "met"
    assert at("E10-1120", 21, 1, 10)["results"]["R3"]["message"] == R3_OVERDUE_TEXT
    assert at("E10-1120", 21, 1, 55)["results"]["R3"]["state"] == "not_met"

    # Bed 7: silent all night -> silence text, no met rule.
    cell7 = at("E07-1120", 20, 19, 0)
    assert cell7["display_text"] == SILENCE_TEXT
    assert all(r["state"] != "met" for r in cell7["results"].values())


# ==========================================================================
# Episodes / inbox ordering and routing.
# ==========================================================================


def test_episodes_and_inbox_sorted_by_time_raised(model: dict) -> None:
    for key in ("episodes", "inbox"):
        times = [item["time_raised"] for item in model[key]]
        assert times == sorted(times), key


def test_episode_routing_doctor_vs_nurse(model: dict) -> None:
    # Doctor episodes are R1 prompts and ONE R2 item for R2a/R2b (D28);
    # nurse inbox is R3 + feed_alert.
    for item in model["episodes"]:
        assert item["rule"] in {R1_RULE_ID, board.R2_GROUP}
    for item in model["inbox"]:
        assert item["rule"] in {R3_RULE_ID, "feed_alert"}
    # Every item exposes the required fields (AC-S4-item) plus the per-episode
    # time bounds the viewer needs to filter episodes known at a selected t.
    for item in [*model["episodes"], *model["inbox"]]:
        assert set(item) >= {
            "bed", "encounter", "rule", "time_raised", "time_ended",
            "start_idx", "end_idx", "workflow_state",
        }
        # Bounds are consistent: start <= end, and time_ended is None (still
        # open at window end) or strictly after time_raised.
        assert item["start_idx"] <= item["end_idx"]
        if item["time_ended"] is not None:
            assert item["time_ended"] > item["time_raised"]


def test_known_episodes_present(model: dict) -> None:
    # Bed 1 R1 prompt raised at 22:20; bed 10 R3 overdue raised at 01:10;
    # bed 9 feed alert raised at 01:15 -- all derived from the engine.
    r1_bed1 = [
        e for e in model["episodes"]
        if e["encounter"] == "E01-1120" and e["rule"] == R1_RULE_ID
    ]
    assert len(r1_bed1) == 1
    assert r1_bed1[0]["time_raised"] == datetime(2026, 11, 20, 22, 20, tzinfo=TZ).isoformat()

    r3_bed10 = [
        i for i in model["inbox"]
        if i["encounter"] == "E10-1120" and i["rule"] == R3_RULE_ID
    ]
    assert len(r3_bed10) == 1
    assert r3_bed10[0]["time_raised"] == datetime(2026, 11, 21, 1, 10, tzinfo=TZ).isoformat()

    feed_bed9 = [
        i for i in model["inbox"]
        if i["encounter"] == "E09-1120" and i["rule"] == "feed_alert"
    ]
    assert len(feed_bed9) == 1
    assert feed_bed9[0]["time_raised"] == datetime(2026, 11, 21, 1, 15, tzinfo=TZ).isoformat()


def test_bed15_has_two_r1_episodes(model: dict) -> None:
    """Bed 15's R1 is met 20:35-20:40, suppressed by a deferral 20:45-01:25,
    then met again from 01:30 -- two distinct episodes (prompts), not one
    collapsed item (finding 1; R1-episodes; data/SCENARIOS.md bed 15)."""

    r1_bed15 = [
        e for e in model["episodes"]
        if e["encounter"] == "E15-1120" and e["rule"] == R1_RULE_ID
    ]
    assert len(r1_bed15) == 2, r1_bed15
    # Ordered by time raised: prompt 1 at 20:35, prompt 2 at 01:30.
    assert r1_bed15[0]["time_raised"] == datetime(2026, 11, 20, 20, 35, tzinfo=TZ).isoformat()
    assert r1_bed15[1]["time_raised"] == datetime(2026, 11, 21, 1, 30, tzinfo=TZ).isoformat()
    # The first episode ends (met run broken by the 20:45 deferral/suppression)
    # before the second is raised -- its time_ended is on or before 01:30.
    assert r1_bed15[0]["time_ended"] is not None
    assert r1_bed15[0]["time_ended"] <= r1_bed15[1]["time_raised"]
    # The two runs do not overlap.
    assert r1_bed15[0]["end_idx"] < r1_bed15[1]["start_idx"]


def test_bed10_r3_episode_workflow_lifecycle(ward: dict, model: dict) -> None:
    """Bed 10's single R3 episode spans the overdue run 01:10-01:50; its
    workflow advances past 'notified' (the 01:12 acknowledgement makes it
    'acknowledged' by the end of the run), and the episode is resolved only at
    the time_ended cell (01:55), never frozen at the first met cell
    (findings 1 & 2; AC-WORKFLOW-1/2; data/SCENARIOS.md bed 10)."""

    r3_bed10 = [
        i for i in model["inbox"]
        if i["encounter"] == "E10-1120" and i["rule"] == R3_RULE_ID
    ]
    assert len(r3_bed10) == 1
    ep = r3_bed10[0]
    assert ep["time_raised"] == datetime(2026, 11, 21, 1, 10, tzinfo=TZ).isoformat()
    # Run ends at 01:50; the first cell after the run is 01:55.
    assert ep["time_ended"] == datetime(2026, 11, 21, 1, 55, tzinfo=TZ).isoformat()
    # Workflow at the end of the run is 'acknowledged' (01:12 ack), not stuck at
    # 'notified'.
    assert ep["workflow_state"] == "acknowledged"

    # The episode's end_idx cell is still met (acknowledging never changes the
    # evaluation state, AC-DEF-2); the time_ended cell is not_met + resolved.
    cells_by_enc = _model_cells_by_encounter(model)
    cells10 = cells_by_enc["E10-1120"]
    end_cell = cells10[ep["end_idx"]]
    assert end_cell["results"]["R3"]["state"] == "met"
    assert end_cell["workflow_states"]["R3"] == "acknowledged"
    resolved_cell = _cell_at(cells10, ep["time_ended"])
    assert resolved_cell["results"]["R3"]["state"] == "not_met"
    assert resolved_cell["workflow_states"]["R3"] == "resolved"


def test_cells_carry_active_occupant_flag(model: dict) -> None:
    """Every serialised cell carries an 'active' occupant flag, and bed 13's two
    encounters each know when they are the one in the bed: E13A active until its
    23:00 discharge, E13B active from its 23:15 admission (finding 3;
    AC-S2-grid; data/SCENARIOS.md bed 13)."""

    cells_by_enc = _model_cells_by_encounter(model)

    # Every cell of every encounter has a boolean active flag.
    for cells in cells_by_enc.values():
        for cell in cells:
            assert isinstance(cell["active"], bool)

    def at(enc: str, d: int, h: int, mi: int) -> dict:
        iso = datetime(2026, 11, d, h, mi, tzinfo=TZ).isoformat()
        return _cell_at(cells_by_enc[enc], iso)

    # E13A: active before the 23:00 discharge, inactive at/after it.
    assert at("E13A-1120", 20, 22, 55)["active"] is True
    assert at("E13A-1120", 20, 23, 0)["active"] is False
    assert at("E13A-1120", 20, 23, 30)["active"] is False

    # E13B: inactive before the 23:15 admission, active from it.
    assert at("E13B-1120", 20, 23, 10)["active"] is False
    assert at("E13B-1120", 20, 23, 15)["active"] is True
    assert at("E13B-1120", 21, 1, 0)["active"] is True

    # A single-occupant bed (bed 1) is active across the whole window.
    assert all(c["active"] is True for c in cells_by_enc["E01-1120"])


# ==========================================================================
# Static copy: verbatim UI strings embedded.
# ==========================================================================


def test_static_copy_is_verbatim(model: dict) -> None:
    static = model["static"]
    assert static["persistent_label"] == board.PERSISTENT_LABEL
    assert static["intended_use"] == board.INTENDED_USE
    assert static["verification"] == board.VERIFICATION
    assert static["ward_line"] == board.WARD_LINE
    assert static["silence_text"] == SILENCE_TEXT
    assert static["r1_met_text"] == R1_MET_TEXT
    assert static["r2_combined_text"] == R2_COMBINED_TEXT
    assert static["r3_overdue_text"] == R3_OVERDUE_TEXT
    assert static["threshold_label"] == board.THRESHOLD_LABEL
    assert static["fluid_unknown_label"] == board.FLUID_UNKNOWN_LABEL


def test_regulatory_copy_is_verbatim_in_evidence(ds: Dataset) -> None:
    """Drift guard (finding 4): the persistent label and the two regulatory
    sentences hardcoded in ``board.py`` must appear **verbatim** in the frozen
    baseline ``docs/EVIDENCE.md``.

    ``test_static_copy_is_verbatim`` only proves the model echoes the
    ``board.*`` attributes, so a silent edit of those attributes would pass it.
    This test anchors them to the signed source so the copy cannot drift from
    the baseline (AC-LABEL-1/2/3). It only **reads** ``docs/EVIDENCE.md``; the
    board never writes to ``docs/`` (safety steering sign-off gate).
    """

    from pathlib import Path

    # tests/ -> repo root -> docs/EVIDENCE.md
    evidence = Path(__file__).resolve().parent.parent / "docs" / "EVIDENCE.md"
    text = evidence.read_text(encoding="utf-8")

    assert board.PERSISTENT_LABEL in text
    assert board.INTENDED_USE in text
    assert board.VERIFICATION in text


# ==========================================================================
# Determinism: building twice gives an identical model.
# ==========================================================================


def test_model_is_deterministic(model: dict) -> None:
    # The shared model (built from the precomputed ward) equals a model built
    # from a fresh load with the engine re-run inside build_board_model: same
    # bytes, no hidden state, and both entry paths agree.
    assert board.build_board_model(load_dataset()) == model


# ==========================================================================
# Property-based tests over synthetic ward results (no real data, no network).
# ==========================================================================

_STATES = list(EvaluationState)
_REASONS = list(ReasonCode)
_WORKFLOWS = list(WorkflowState)

_grid_times = st.just(
    [datetime(2026, 11, 20, 19, 0, tzinfo=TZ) + timedelta(minutes=5 * i)
     for i in range(4)]
)

# In-memory templates for the synthetic (dataset, ward) pairs. These never
# touch the real dataset or any file; they exist only so hypothesis can build
# arbitrary GridCells and feed them through build_board_model.
_ENC_TEMPLATE = Encounter(
    bed=1,
    encounter="E",
    age=60,
    sex="M",
    weight_kg=70,
    code_status="full",
    pathways=(),
    anuric=False,
    scenario="synthetic",
)

_DS_TEMPLATE = Dataset(
    meta={},
    encounters=(),
    observations=(),
    infusions=(),
    events=(),
    fluids=(),
    daily_totals=(),
    by_encounter={},
    by_bed={},
)


def _rule_result(rule_id: str, state: EvaluationState, reason: ReasonCode) -> RuleResult:
    message = R1_MET_TEXT if (state is EvaluationState.MET and rule_id == R1_RULE_ID) else ""
    return RuleResult(
        rule_id=rule_id,
        state=state,
        reason=reason,
        detail="synthetic-detail",
        message=message,
    )


@st.composite
def _synthetic_ward(draw) -> tuple[Dataset, dict]:
    """Build a tiny synthetic (dataset, ward-results) pair.

    Three encounters across two beds (bed 2 is a reassignment carrying two
    encounters, like the real bed 13) so ordering and multi-encounter handling
    are exercised without touching the real dataset.
    """

    times = draw(_grid_times)
    # Fixed, in-memory encounters; weights/pathways irrelevant to serialisation.
    enc_specs = [(1, "EA"), (2, "EB1"), (2, "EB2")]
    encounters = tuple(
        dataclasses.replace(
            _ENC_TEMPLATE, bed=bed, encounter=enc
        )
        for bed, enc in enc_specs
    )
    ds = dataclasses.replace(
        _DS_TEMPLATE,
        encounters=encounters,
        by_encounter={e.encounter: e for e in encounters},
        by_bed={
            1: (encounters[0],),
            2: (encounters[1], encounters[2]),
        },
    )

    results: dict[str, list[GridCell]] = {}
    for enc in encounters:
        cells: list[GridCell] = []
        for t in times:
            per_rule: dict[str, RuleResult] = {}
            for rule_id in RULE_IDS:
                state = draw(st.sampled_from(_STATES))
                reason = draw(st.sampled_from(_REASONS))
                per_rule[rule_id] = _rule_result(rule_id, state, reason)
            feed = draw(st.booleans())
            any_met = any(r.state is EvaluationState.MET for r in per_rule.values())
            cells.append(
                GridCell(
                    bed=enc.bed,
                    encounter=enc.encounter,
                    t=t,
                    results=per_rule,
                    combined_message="",
                    feed_alert=feed,
                    display_text="" if any_met else SILENCE_TEXT,
                    workflow_states={R3_RULE_ID: draw(st.sampled_from(_WORKFLOWS))},
                )
            )
        results[enc.encounter] = cells
    return ds, results


@given(pair=_synthetic_ward())
@settings(max_examples=60)
def test_pbt_cells_serialise_verbatim(pair) -> None:
    """For any synthetic ward, every embedded cell equals its GridCell and
    every enum serialises to its verbatim .value word (no recomputation)."""

    ds, results = pair
    model = board.build_board_model(ds, results)
    cells_by_enc = _model_cells_by_encounter(model)
    for enc, grid_cells in results.items():
        model_cells = cells_by_enc[enc]
        assert len(model_cells) == len(grid_cells)
        for mcell, gcell in zip(model_cells, grid_cells):
            assert mcell["t"] == gcell.t.isoformat()
            assert mcell["feed_alert"] == gcell.feed_alert
            assert mcell["display_text"] == gcell.display_text
            # Every cell carries a boolean active flag (finding 3); the
            # synthetic encounters have no admission/discharge events, so
            # r3.is_active is True throughout.
            assert mcell["active"] is True
            for rule_id, gr in gcell.results.items():
                mr = mcell["results"][rule_id]
                assert mr["state"] == gr.state.value
                assert mr["reason"] == gr.reason.value
                assert mr["detail"] == gr.detail
                assert mr["message"] == gr.message
            for rule_id, ws in gcell.workflow_states.items():
                assert mcell["workflow_states"][rule_id] == ws.value


@given(pair=_synthetic_ward())
@settings(max_examples=60)
def test_pbt_beds_ordered_and_episodes_time_sorted(pair) -> None:
    """For any synthetic ward, beds come out in bed-number order and the
    episode/inbox lists are sorted by time raised."""

    ds, results = pair
    model = board.build_board_model(ds, results)

    numbers = [bed["bed"] for bed in model["beds"]]
    assert numbers == sorted(numbers)

    # The reassignment bed carries both of its encounters.
    bed2 = next(b for b in model["beds"] if b["bed"] == 2)
    assert set(bed2["encounters"]) == {"EB1", "EB2"}

    for key in ("episodes", "inbox"):
        times = [item["time_raised"] for item in model[key]]
        assert times == sorted(times), key


@given(pair=_synthetic_ward())
@settings(max_examples=30)
def test_pbt_model_is_json_serialisable_and_deterministic(pair) -> None:
    """The model is a plain JSON-safe structure and building it twice from the
    same inputs gives an identical result (determinism, AC-GEN-7)."""

    import json

    ds, results = pair
    first = board.build_board_model(ds, results)
    second = board.build_board_model(ds, results)
    assert first == second
    # Canonical JSON dump must succeed (only str/int/bool/None/list/dict).
    dumped = json.dumps(first, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert isinstance(dumped, str)


def test_bed6_r2a_and_r2b_are_one_doctor_item(model: dict) -> None:
    """R2a (met 01:05) and R2b (met 02:00) on bed 6 form ONE R2 doctor item
    raised at 01:05 whose cells carry the combined message from 02:00 (D28;
    design.md §3c; data/SCENARIOS.md bed 6). No separate R2a/R2b items."""

    r2_bed6 = [e for e in model["episodes"] if e["encounter"] == "E06-1120"]
    assert [e["rule"] for e in r2_bed6] == [board.R2_GROUP]
    item = r2_bed6[0]
    assert item["time_raised"] == datetime(2026, 11, 21, 1, 5, tzinfo=TZ).isoformat()
    cells = next(
        b["encounters"]["E06-1120"]["cells"] for b in model["beds"] if b["bed"] == 6
    )
    grid = model["grid_times"]
    at_0200 = grid.index(datetime(2026, 11, 21, 2, 0, tzinfo=TZ).isoformat())
    assert item["start_idx"] < at_0200 <= item["end_idx"]
    assert cells[at_0200]["combined_message"] == R2_COMBINED_TEXT
    assert cells[at_0200 - 1]["combined_message"] == ""
